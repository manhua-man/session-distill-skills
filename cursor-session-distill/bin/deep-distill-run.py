#!/usr/bin/env python3
"""Cursor Deep Distill batch runner (Grok paradigm)."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import deep_distill_lib as ddl

SCRIPT = Path(__file__).resolve().parent / "cursor-session-distill.py"
spec = importlib.util.spec_from_file_location("cursor_sd", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

QUEUE_FILE = mod.DISTILL_DIR / "servers-deep-queue.md"
ANSWER_DIR = mod.DISTILL_DIR / "distilled" / "answer-packets"
CHECK_WORK_DIR = mod.DISTILL_DIR / "distilled" / "check-work"
PACKET_PREFIX = "cursor-"


def load_servers_sessions() -> list[dict]:
    manifest = mod.load_manifest()
    sessions = [
        s
        for s in manifest.get("sessions", [])
        if "servers" in (s.get("workspace") or "").lower()
    ]
    return sorted(sessions, key=lambda s: s.get("created_at") or "")


def session_index(sessions: list[dict]) -> dict[str, dict]:
    return {s["session_id"]: s for s in sessions}


def packet_path(session_id: str) -> Path:
    return mod.PACKETS_DIR / f"{PACKET_PREFIX}{session_id}.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cursor deep distill batch runner")
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--force-bundle", action="store_true", default=True)
    parser.add_argument("--session-ids", nargs="*", default=[])
    parser.add_argument("--project", type=str, default="servers")
    args = parser.parse_args()

    mod.ensure_dirs()
    ANSWER_DIR.mkdir(parents=True, exist_ok=True)
    CHECK_WORK_DIR.mkdir(parents=True, exist_ok=True)

    sessions = load_servers_sessions()
    if args.session_ids:
        by_id = session_index(sessions)
        batch = [by_id[sid] for sid in args.session_ids if sid in by_id]
    else:
        batch = sessions[args.offset : args.offset + args.batch_size]

    if not batch:
        print("No sessions in batch")
        return 1

    ids = [s["session_id"] for s in batch]
    print(f"==> Cursor deep distill batch: {len(batch)} sessions (offset={args.offset})")
    for s in batch:
        print(f"  - {s['session_id']} {(s.get('name') or '')[:60]}")

    if args.force_bundle:
        mod.cmd_bundle(next_count=0, force=True, session_ids=ids)

    for meta in batch:
        sid = meta["session_id"]
        path = packet_path(sid)
        if not path.exists():
            print(f"missing packet: {path}")
            continue
        packet_text = path.read_text(encoding="utf-8", errors="replace")
        claims = ddl.extract_claims(packet_text, meta)
        questions = ddl.default_questions(claims)
        out = ANSWER_DIR / f"{sid}.md"
        out.write_text(
            ddl.render_answer_packet(
                sid,
                meta,
                claims,
                questions,
                platform="cursor",
                project_path=meta.get("workspace", ""),
            ),
            encoding="utf-8",
        )
        print(f"  -> claims={len(claims)} answer-packet={out}")

    batch_label = f"Cursor batch offset {args.offset} ({len(batch)} sessions)"
    report = ddl.render_check_work_report(
        batch_label=batch_label,
        session_ids=ids,
        promoted=[],
        not_promoted=[],
        verdict="PENDING",
    )
    report_path = CHECK_WORK_DIR / f"batch-offset-{args.offset}-report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"==> check-work stub: {report_path}")
    print("==> Next: answer-me verify each Q → promote ANSWERED only → update check-work → mark distilled")
    print(f"==> Queue file: {QUEUE_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
