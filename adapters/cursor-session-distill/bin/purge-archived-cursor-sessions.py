#!/usr/bin/env python3
"""Purge archived and distilled servers sessions from Cursor state.vscdb + session-distill manifest.

必须在 Cursor 完全退出后运行（运行中的 Cursor 会把内存里的会话状态写回 sqlite，
外部删除会被还原）。脚本会先检查 Cursor 进程，未退出时拒绝执行（--force 可跳过）。

清理范围（默认 servers 项目，可用环境变量覆盖）：
  1. composerHeaders 表  删除 workspaceId 匹配的 isArchived=1 行
  2. composer.composerHeaders（ItemTable）移除匹配项目的 archived/distilled 条目
  3. cursorDiskKV 清理上述 composerId 的残留键（checkpointId/ofsContent/composerData/bubbleId 等）
  4. cursor-manifest.json 移除匹配项目的 archived/distilled 会话记录

幂等：可重复运行；自动创建 state.vscdb 备份。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_HASH = os.environ.get("CURSOR_WORKSPACE_HASH", "6b9889124694a055e87bfe1ba92e1f01")  # servers
WORKSPACE_PATH = os.environ.get("CURSOR_WORKSPACE_PATH", r"e:\project\servers").lower()

CURSOR_DB = Path(os.environ.get(
    "CURSOR_DB_PATH",
    Path.home() / "AppData" / "Roaming" / "Cursor" / "User" / "globalStorage" / "state.vscdb",
))
DISTILL_DIR = Path(os.environ.get("CURSOR_DISTILL_DIR", Path.home() / ".cursor" / "session-distill"))
MANIFEST = DISTILL_DIR / "cursor-manifest.json"


def cursor_running() -> bool:
    """Cursor 进程是否在运行（Windows tasklist 检查）。"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Cursor.exe"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        return "Cursor.exe" in out
    except Exception:
        return False


def get_distilled_session_ids() -> set[str]:
    """获取所有已标记 distilled 的 session_id。"""
    if not MANIFEST.exists():
        return set()
    try:
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return {
            s["session_id"] for s in m.get("sessions", [])
            if s.get("status") == "distilled" or s.get("is_archived")
        }
    except Exception:
        return set()


def backup_db() -> Path | None:
    if not CURSOR_DB.exists():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak_path = CURSOR_DB.with_name(f"{CURSOR_DB.name}.backup-purge-{ts}")
    shutil.copy2(CURSOR_DB, bak_path)
    print(f"backup: {bak_path}")
    return bak_path


def purge_sqlite() -> dict[str, int]:
    import sqlite3

    distilled_ids = get_distilled_session_ids()
    stats = {"composerHeaders_deleted": 0, "allComposers_removed": 0, "kv_keys_deleted": 0}
    conn = sqlite3.connect(str(CURSOR_DB), timeout=60)
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")

    # 1) composerHeaders 表：删除匹配项目的 archived 行
    try:
        cur.execute(
            "SELECT composerId FROM composerHeaders WHERE workspaceId=? AND isArchived=1",
            (WORKSPACE_HASH,),
        )
        arch_ids = set(r[0] for r in cur.fetchall())
        cur.execute(
            "DELETE FROM composerHeaders WHERE workspaceId=? AND isArchived=1",
            (WORKSPACE_HASH,),
        )
        stats["composerHeaders_deleted"] = cur.rowcount
    except Exception:
        arch_ids = set()

    # 合并已蒸馏会话 ID
    all_target_ids = arch_ids | distilled_ids

    # 2) ItemTable composer.composerHeaders & composer.composerData：移除匹配项目的 archived/distilled 条目
    for item_key in ("composer.composerHeaders", "composer.composerData"):
        cur.execute("SELECT value FROM ItemTable WHERE key=?", (item_key,))
        row = cur.fetchone()
        if row and row[0]:
            try:
                payload = json.loads(row[0])
                allc = payload.get("allComposers", [])
                kept = []
                for h in allc:
                    cid = h.get("composerId") or h.get("id")
                    ws_obj = (h.get("workspaceIdentifier") or {}).get("uri", {})
                    fs = ws_obj.get("fsPath") or ws_obj.get("path") if isinstance(ws_obj, dict) else str(ws_obj or "")
                    is_servers = WORKSPACE_PATH in str(fs).lower()
                    
                    # 删除条件：匹配 servers 且为 (已归档 OR 已蒸馏)
                    if is_servers and (h.get("isArchived") or cid in all_target_ids):
                        continue
                    kept.append(h)

                removed = len(allc) - len(kept)
                if removed:
                    stats["allComposers_removed"] += removed
                    payload["allComposers"] = kept
                    cur.execute(
                        "UPDATE ItemTable SET value=? WHERE key=?",
                        (json.dumps(payload, ensure_ascii=False), item_key),
                    )
            except Exception:
                pass

    # 3) 高速批量清理 cursorDiskKV：单次全表键名扫描，避免数千次 LIKE 全表扫描
    print("Scanning cursorDiskKV keys for target composer IDs...", flush=True)
    cur.execute("SELECT key FROM cursorDiskKV")
    all_kv_keys = [r[0] for r in cur.fetchall()]
    
    prefixes = ("checkpointId:", "ofsContent:", "composerVirtualRowHeights:", "codeBlockPartialInlineDiffFates:", "composerData:", "bubbleId:")
    keys_to_delete = []
    
    for k in all_kv_keys:
        if k.startswith(prefixes):
            # Check if any target cid is in key
            for cid in all_target_ids:
                if cid in k:
                    keys_to_delete.append(k)
                    break

    print(f"Deleting {len(keys_to_delete)} matching keys from cursorDiskKV...", flush=True)
    # Batch delete
    batch_size = 900
    for i in range(0, len(keys_to_delete), batch_size):
        batch = keys_to_delete[i:i+batch_size]
        placeholders = ','.join('?' for _ in batch)
        cur.execute(f"DELETE FROM cursorDiskKV WHERE key IN ({placeholders})", batch)
        stats["kv_keys_deleted"] += cur.rowcount

    conn.commit()
    conn.close()
    stats["total_purged_ids"] = len(all_target_ids)
    return stats


def purge_manifest() -> tuple[int, int]:
    if not MANIFEST.exists():
        return 0, 0
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sessions = m.get("sessions", [])
    before = len(sessions)
    kept = [
        s for s in sessions
        if not (s.get("status") == "distilled" and WORKSPACE_PATH in (s.get("workspace") or "").lower())
    ]
    m["sessions"] = kept
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return before - len(kept), before


def purge_search_db() -> dict[str, int]:
    import sqlite3
    search_db = CURSOR_DB.with_name("conversation-search.db")
    stats = {"search_conversations_deleted": 0}
    if not search_db.exists():
        return stats
    try:
        conn = sqlite3.connect(str(search_db), timeout=60)
        cur = conn.cursor()
        cur.execute("SELECT id FROM conversations WHERE is_archived = 1")
        arch_ids = [r[0] for r in cur.fetchall()]
        if arch_ids:
            cur.execute("DELETE FROM conversations WHERE is_archived = 1")
            stats["search_conversations_deleted"] = cur.rowcount
            cur.executemany("DELETE FROM conversation_search_candidates WHERE id = ?", [(aid,) for aid in arch_ids])
            try:
                cur.execute("INSERT INTO conversation_fts(conversation_fts) VALUES('rebuild')")
            except Exception:
                pass
            conn.commit()
            conn.execute("VACUUM")
        conn.close()
    except Exception as e:
        print(f"Note on conversation-search.db: {e}")
    return stats


def purge_workspace_storage() -> int:
    import sqlite3
    ws_dir = CURSOR_DB.parent.parent / "workspaceStorage"
    deleted = 0
    if not ws_dir.exists():
        return deleted
    for root, dirs, files in os.walk(ws_dir):
        for f in files:
            if f.endswith(".vscdb"):
                p = Path(root) / f
                try:
                    conn = sqlite3.connect(str(p), timeout=30)
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = [r[0] for r in cur.fetchall()]
                    if "ItemTable" in tables:
                        cur.execute("DELETE FROM ItemTable WHERE key LIKE '%composerChatViewPane%' OR key LIKE '%composer.composerHeaders%' OR key LIKE '%composer.composerData%'")
                        cnt = cur.rowcount
                        if cnt > 0:
                            deleted += cnt
                            conn.commit()
                            conn.execute("VACUUM")
                    conn.close()
                except Exception:
                    pass
    return deleted


def verify() -> None:
    import sqlite3

    conn = sqlite3.connect(str(CURSOR_DB), timeout=30)
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM composerHeaders WHERE workspaceId=? AND isArchived=1", (WORKSPACE_HASH,))
        remaining = cur.fetchone()[0]
        print(f"verify: composerHeaders archived remaining (workspace): {remaining}")
    except Exception:
        pass
    
    cur.execute("SELECT value FROM ItemTable WHERE key='composer.composerHeaders'")
    row = cur.fetchone()
    if row:
        payload = json.loads(row[0])
        allc = payload.get("allComposers", [])
        servers_left = [
            h for h in allc
            if WORKSPACE_PATH in str((h.get("workspaceIdentifier") or {}).get("uri", {})).lower()
        ]
        print(f"verify: servers composers remaining in allComposers: {len(servers_left)}")
    conn.close()

    search_db = CURSOR_DB.with_name("conversation-search.db")
    if search_db.exists():
        try:
            s_conn = sqlite3.connect(str(search_db), timeout=30)
            s_cur = s_conn.cursor()
            s_cur.execute("SELECT COUNT(*) FROM conversations WHERE is_archived = 1")
            arch_cnt = s_cur.fetchone()[0]
            print(f"verify: conversation-search.db archived remaining: {arch_cnt}")
            s_conn.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge archived sessions (run with Cursor closed)")
    parser.add_argument("--force", action="store_true", help="跳过 Cursor 进程检查")
    parser.add_argument("--skip-manifest", action="store_true", help="只清 sqlite，不动 manifest")
    args = parser.parse_args()

    if not CURSOR_DB.exists():
        print(f"Error: Cursor DB not found: {CURSOR_DB}")
        return 1
    if not args.force and cursor_running():
        print("Error: Cursor 正在运行。请完全退出 Cursor（含托盘进程）后重跑，否则删除会被还原。")
        print("      确认已退出后仍报此错，可加 --force 跳过检查。")
        return 1

    print(f"db: {CURSOR_DB}")
    print(f"manifest: {MANIFEST}")
    print(f"workspace: hash={WORKSPACE_HASH} path={WORKSPACE_PATH}")

    backup_db()
    stats = purge_sqlite()
    print(f"sqlite: {stats}")

    search_stats = purge_search_db()
    print(f"search_db: {search_stats}")

    ws_keys_deleted = purge_workspace_storage()
    print(f"workspace_storage_deleted: {ws_keys_deleted}")

    transcripts_deleted = purge_agent_transcripts()
    print(f"agent_transcripts_deleted: {transcripts_deleted}")

    if not args.skip_manifest:
        removed, before = purge_manifest()
        print(f"manifest: distilled removed={removed} (before={before}, after={before - removed})")

    verify()
    print("Done. 重新打开 Cursor 即可看到 Archived 会话清空。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())