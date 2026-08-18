#!/usr/bin/env python3
"""Purge archived servers sessions from Cursor state.vscdb + session-distill manifest.

必须在 Cursor 完全退出后运行（运行中的 Cursor 会把内存里的会话状态写回 sqlite，
外部删除会被还原）。脚本会先检查 Cursor 进程，未退出时拒绝执行（--force 可跳过）。

清理范围（默认 servers 项目，可用环境变量覆盖）：
  1. composerHeaders 表  删除 workspaceId 匹配的 isArchived=1 行（servers 约 78 条）
  2. composer.composerHeaders（ItemTable）移除匹配项目的 archived 条目（servers 约 150 条）
  3. cursorDiskKV 清理上述 composerId 的残留键（checkpointId/ofsContent 等）
  4. cursor-manifest.json 移除匹配项目的 archived 会话记录（servers 约 218 条）

幂等：可重复运行；备份见 state.vscdb.backup-archived-clean-20260812T025811Z（已存在）。

环境变量覆盖：
  CURSOR_WORKSPACE_HASH  workspace hash（默认 servers 6b988912...）
  CURSOR_WORKSPACE_PATH  workspace fsPath（默认 e:\\project\\servers）
  CURSOR_DB_PATH         state.vscdb 路径
  CURSOR_DISTILL_DIR     数据目录（含 cursor-manifest.json）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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
        # 非 Windows 或 tasklist 不可用：不阻塞（依赖用户自行退出 Cursor）
        return False


def purge_sqlite() -> dict[str, int]:
    import sqlite3

    stats = {"composerHeaders_deleted": 0, "allComposers_removed": 0, "kv_keys_deleted": 0}
    conn = sqlite3.connect(str(CURSOR_DB), timeout=60)
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")

    # 1) composerHeaders 表：删除匹配项目的 archived 行
    cur.execute(
        "SELECT composerId FROM composerHeaders WHERE workspaceId=? AND isArchived=1",
        (WORKSPACE_HASH,),
    )
    arch_ids = [r[0] for r in cur.fetchall()]
    cur.execute(
        "DELETE FROM composerHeaders WHERE workspaceId=? AND isArchived=1",
        (WORKSPACE_HASH,),
    )
    stats["composerHeaders_deleted"] = cur.rowcount

    # 2) ItemTable composer.composerHeaders：移除匹配项目的 archived 条目
    cur.execute("SELECT value FROM ItemTable WHERE key='composer.composerHeaders'")
    row = cur.fetchone()
    if row:
        payload = json.loads(row[0])
        allc = payload.get("allComposers", [])
        kept = [
            h for h in allc
            if not (
                (h.get("workspaceIdentifier") or {}).get("uri", {}).get("fsPath", "").lower() == WORKSPACE_PATH
                and h.get("isArchived")
            )
        ]
        stats["allComposers_removed"] = len(allc) - len(kept)
        if stats["allComposers_removed"]:
            payload["allComposers"] = kept
            cur.execute(
                "UPDATE ItemTable SET value=? WHERE key='composer.composerHeaders'",
                (json.dumps(payload, ensure_ascii=False),),
            )

    # 3) cursorDiskKV：清理这些 composerId 的残留键
    for cid in arch_ids:
        for prefix in ("checkpointId", "ofsContent", "composerVirtualRowHeights", "codeBlockPartialInlineDiffFates"):
            cur.execute("DELETE FROM cursorDiskKV WHERE key LIKE ?", (f"{prefix}:{cid}%",))
            stats["kv_keys_deleted"] += cur.rowcount

    conn.commit()
    conn.close()
    stats["archived_ids"] = len(arch_ids)
    return stats


def purge_manifest() -> tuple[int, int]:
    if not MANIFEST.exists():
        return 0, 0
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sessions = m.get("sessions", [])
    before = len(sessions)
    kept = [
        s for s in sessions
        if not (s.get("is_archived") and WORKSPACE_PATH in (s.get("workspace") or "").lower())
    ]
    m["sessions"] = kept
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return before - len(kept), before


def verify() -> None:
    import sqlite3

    conn = sqlite3.connect(str(CURSOR_DB), timeout=30)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM composerHeaders WHERE workspaceId=? AND isArchived=1", (WORKSPACE_HASH,))
    remaining = cur.fetchone()[0]
    conn.close()
    print(f"verify: composerHeaders archived remaining (workspace): {remaining}")
    if remaining:
        print("WARNING: 仍有残留 archived 行。若 Cursor 未完全退出，其内存状态可能已写回，请退出后重跑。")
    else:
        print("verify: OK - archived rows cleaned")


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

    stats = purge_sqlite()
    print(f"sqlite: {stats}")

    if not args.skip_manifest:
        removed, before = purge_manifest()
        print(f"manifest: archived removed={removed} (before={before}, after={before - removed})")

    verify()
    print("Done. 重新打开 Cursor 即可看到 Archived 会话消失。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())