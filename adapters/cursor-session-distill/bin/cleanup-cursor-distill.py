#!/usr/bin/env python3
"""Cleanup Cursor session-distill artifacts after Deep Distill.

Subcommands:
  workspace  - remove packets / answer-packets / check-work (keep manifest)
  jsonl      - remove agent-transcripts dirs for distilled sessions
  sqlite     - purge Composer rows from globalStorage state.vscdb
  all        - workspace + jsonl + sqlite

Examples:
  python cleanup-cursor-distill.py all --project servers
  python cleanup-cursor-distill.py jsonl --keep <current-session-id>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DISTILL_DIR = Path(os.environ.get("CURSOR_DISTILL_DIR", Path.home() / ".cursor" / "session-distill"))
MANIFEST = DISTILL_DIR / "cursor-manifest.json"
# 与 cursor-session-distill.py 的 CURSOR_JSONL_TRANSCRIPTS_DIR 保持一致：
# 转录按 workspace slug 分目录，servers 落在 e-project-servers/agent-transcripts
TRANSCRIPT_ROOT = Path(os.environ.get(
    "CURSOR_TRANSCRIPT_ROOT",
    Path.home() / ".cursor" / "projects" / "e-project-servers" / "agent-transcripts",
))
CURSOR_DB_PATH = Path(os.environ.get("CURSOR_DB_PATH", Path.home() / "AppData" / "Roaming" / "Cursor" / "User" / "globalStorage" / "state.vscdb"))
REPO_KB = Path(os.environ.get("SESSION_DISTILL_REPO_KB", "session-knowledge-base.md"))
PACKET_PREFIX = "cursor-"


def parse_keep_ids(values: list[str]) -> set[str]:
    keep: set[str] = set()
    for raw in values:
        keep.update(part.strip() for part in raw.split(",") if part.strip())
    return keep


def load_manifest() -> dict:
    if not MANIFEST.exists():
        raise FileNotFoundError(f"manifest not found: {MANIFEST}")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def project_filter(session: dict, project: str) -> bool:
    workspace = (session.get("workspace") or "").lower()
    return project.lower() in workspace


def processed_sessions(manifest: dict, *, project: str) -> list[dict]:
    """无状态识别「已处理」会话：packet 文件存在即视为已蒸馏（与 deep-distill-run 判据一致）。

    stateless 流程不做 mark distilled，manifest status 始终是 bundled/new；
    packet 文件（packets/cursor-<sid>.md）是唯一的去重标记。
    """
    packets_dir = DISTILL_DIR / "packets"
    return [
        s
        for s in manifest.get("sessions", [])
        if project_filter(s, project)
        and (packets_dir / f"{PACKET_PREFIX}{s.get('session_id')}.md").exists()
    ]


def append_log(section: str, lines: list[str]) -> None:
    log = DISTILL_DIR / "cleanup-log.txt"
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\n--- {section} ---\n")
        for line in lines:
            f.write(line + "\n")


def cmd_workspace(project: str, sessions: list[dict], total_project: int) -> int:
    ids = {s["session_id"] for s in sessions}
    distilled_count = len(ids)

    removed_packets = 0
    removed_answers = 0
    removed_notes = 0

    packets_dir = DISTILL_DIR / "packets"
    for sid in ids:
        for path in packets_dir.glob(f"{PACKET_PREFIX}{sid}*.md"):
            path.unlink(missing_ok=True)
            removed_packets += 1

    for sub, is_answer in (("distilled/answer-packets", True), ("distilled/sessions", False)):
        dir_path = DISTILL_DIR / sub
        for sid in ids:
            path = dir_path / f"{sid}.md"
            if path.exists():
                path.unlink()
                if is_answer:
                    removed_answers += 1
                else:
                    removed_notes += 1

    removed_reports = 0
    check_work = DISTILL_DIR / "distilled" / "check-work"
    if check_work.exists():
        for path in list(check_work.glob("*.md")):
            path.unlink()
            removed_reports += 1

    append_log(
        "workspace cleanup",
        [
            f"project: {project}",
            f"processed_ids: {distilled_count}",
            f"project_total: {total_project}",
            f"removed_packets: {removed_packets}",
            f"removed_answer_packets: {removed_answers}",
            f"removed_session_notes: {removed_notes}",
            f"removed_check_work_reports: {removed_reports}",
        ],
    )
    print(
        f"workspace: processed={distilled_count} project_total={total_project} "
        f"packets={removed_packets} answers={removed_answers} notes={removed_notes} "
        f"reports={removed_reports}"
    )
    return 0


def cmd_jsonl(project: str, keep_ids: set[str], sessions: list[dict]) -> int:
    ids = [
        s["session_id"]
        for s in sessions
        if s["session_id"] not in keep_ids
    ]

    deleted_dirs: list[str] = []
    missing_dirs: list[str] = []
    for sid in ids:
        path = TRANSCRIPT_ROOT / sid
        if path.is_dir():
            shutil.rmtree(path)
            deleted_dirs.append(sid)
        else:
            missing_dirs.append(sid)

    append_log(
        "jsonl cleanup",
        [
            f"project: {project}",
            f"deleted_dirs: {len(deleted_dirs)}",
            f"no_jsonl_dir: {len(missing_dirs)}",
            f"kept: {sorted(keep_ids)}",
            *[f"  deleted: {sid}" for sid in deleted_dirs],
        ],
    )
    print(f"jsonl: deleted={len(deleted_dirs)} missing_dir={len(missing_dirs)} kept={len(keep_ids)}")
    return 0


def backup_db(db_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = db_path.with_name(f"state.vscdb.backup-distill-{stamp}")
    shutil.copy2(db_path, backup)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, Path(str(backup) + suffix))
    return backup


def purge_sqlite(composer_ids: list[str]) -> dict[str, int]:
    stats = {
        "composer_headers_table": 0,
        "composer_data": 0,
        "bubbles": 0,
        "panel_hidden": 0,
        "headers_json_removed": 0,
    }
    conn = sqlite3.connect(CURSOR_DB_PATH, timeout=30)
    cur = conn.cursor()
    id_set = set(composer_ids)

    cur.execute("SELECT value FROM ItemTable WHERE key = 'composer.composerHeaders'")
    row = cur.fetchone()
    if row:
        payload = json.loads(row[0])
        composers = payload.get("allComposers", [])
        kept = [h for h in composers if h.get("composerId") not in id_set]
        stats["headers_json_removed"] = len(composers) - len(kept)
        if stats["headers_json_removed"]:
            payload["allComposers"] = kept
            cur.execute(
                "UPDATE ItemTable SET value = ? WHERE key = 'composer.composerHeaders'",
                (json.dumps(payload, ensure_ascii=False),),
            )

    for sid in composer_ids:
        cur.execute("DELETE FROM composerHeaders WHERE composerId = ?", (sid,))
        stats["composer_headers_table"] += cur.rowcount
        cur.execute("DELETE FROM cursorDiskKV WHERE key = ?", (f"composerData:{sid}",))
        stats["composer_data"] += cur.rowcount
        cur.execute("DELETE FROM cursorDiskKV WHERE key LIKE ?", (f"bubbleId:{sid}:%",))
        stats["bubbles"] += cur.rowcount
        panel_key = f"workbench.panel.composerChatViewPane.{sid}.hidden"
        cur.execute("DELETE FROM ItemTable WHERE key = ?", (panel_key,))
        stats["panel_hidden"] += cur.rowcount

    conn.commit()
    conn.close()
    return stats


def cmd_sqlite(project: str, keep_ids: set[str], sessions: list[dict]) -> int:
    if not CURSOR_DB_PATH.exists():
        print(f"Error: Cursor DB not found: {CURSOR_DB_PATH}")
        return 1

    ids = [
        s["session_id"]
        for s in sessions
        if s["session_id"] not in keep_ids
    ]
    if not ids:
        print("sqlite: no processed composer IDs to purge")
        return 0

    size_before = CURSOR_DB_PATH.stat().st_size
    backup = backup_db(CURSOR_DB_PATH)
    print(f"sqlite backup: {backup}")

    try:
        stats = purge_sqlite(ids)
    except sqlite3.OperationalError as exc:
        print(f"SQLite error (close Cursor and retry): {exc}")
        return 1

    size_after = CURSOR_DB_PATH.stat().st_size
    append_log(
        "sqlite cleanup",
        [
            f"project: {project}",
            f"purged_ids: {len(ids)}",
            *[f"{k}: {v}" for k, v in stats.items()],
            f"db_bytes_before: {size_before}",
            f"db_bytes_after: {size_after}",
            f"kept: {sorted(keep_ids)}",
        ],
    )
    print(f"sqlite: purged={len(ids)} stats={stats}")
    print("Note: run VACUUM after closing Cursor to reclaim disk space.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup Cursor session-distill artifacts")
    parser.add_argument("command", choices=["workspace", "jsonl", "sqlite", "all"])
    parser.add_argument("--project", default="servers")
    parser.add_argument(
        "--keep",
        action="append",
        default=[],
        help="Composer/session IDs to keep (comma-separated or repeat flag)",
    )
    args = parser.parse_args()
    keep_ids = parse_keep_ids(args.keep)

    # 会话列表只计算一次：workspace 清理会删除 packet 文件，
    # 若 jsonl/sqlite 重新按 packet 判据计算，就会选不到任何会话。
    manifest = load_manifest()
    sessions = processed_sessions(manifest, project=args.project)
    total_project = sum(1 for s in manifest.get("sessions", []) if project_filter(s, args.project))

    if args.command in {"workspace", "all"}:
        code = cmd_workspace(args.project, sessions, total_project)
        if code:
            return code
    if args.command in {"jsonl", "all"}:
        code = cmd_jsonl(args.project, keep_ids, sessions)
        if code:
            return code
    if args.command in {"sqlite", "all"}:
        code = cmd_sqlite(args.project, keep_ids, sessions)
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
