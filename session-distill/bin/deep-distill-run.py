#!/usr/bin/env python3
"""Claude Code Deep Distill batch runner (Grok paradigm)."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import deep_distill_lib as ddl

SCRIPT = Path(__file__).resolve().parent / "session-distill.py"
spec = importlib.util.spec_from_file_location("claude_sd", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ANSWER_DIR = mod.DISTILL_DIR / "distilled" / "answer-packets"
CHECK_WORK_DIR = mod.DISTILL_DIR / "distilled" / "check-work"
QUEUE_FILE = mod.DISTILL_DIR / "servers-deep-queue.md"


def load_servers_sessions() -> list[dict]:
    manifest = mod.load_manifest()
    sessions = [
        s for s in manifest.get("sessions", [])
        if "servers" in (s.get("cwd") or s.get("project_path") or "").lower()
    ]
    return sorted(sessions, key=lambda s: s.get("timestamp") or "")


def session_index(sessions: list[dict]) -> dict[str, dict]:
    return {s["session_id"]: s for s in sessions}


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude deep distill batch runner")
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--force-bundle", action="store_true", default=True)
    parser.add_argument("--session-ids", nargs="*", default=[])
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
    print(f"==> Claude deep distill batch: {len(batch)} sessions (offset={args.offset})")
    for s in batch:
        title = (s.get("thread_name") or s.get("name") or "")[:60]
        print(f"  - {s['session_id']} {title}")

    if args.force_bundle:
        manifest = mod.load_manifest()
        by_id = {s["session_id"]: s for s in manifest.get("sessions", [])}
        for sid in ids:
            session = by_id.get(sid)
            if not session:
                continue
            packet_path = mod.PACKETS_DIR / f"{sid}.md"
            print(f"  -> bundle {sid}")
            mod.generate_packet(session, packet_path)
            session["status"] = "bundled"
            session["bundle_path"] = str(packet_path)
        manifest["updated_at"] = mod.now_iso()
        mod.save_manifest(manifest)

    for meta in batch:
        sid = meta["session_id"]
        path = mod.PACKETS_DIR / f"{sid}.md"
        if not path.exists():
            print(f"missing packet: {path}")
            continue
        packet_text = path.read_text(encoding="utf-8", errors="replace")
        claims = ddl.extract_claims(packet_text, meta)
        questions = ddl.default_questions(claims)
        out = ANSWER_DIR / f"{sid}.md"
        out.write_text(
            ddl.render_answer_packet(
                sid, meta, claims, questions,
                platform="claude",
                project_path=meta.get("cwd") or "",
            ),
            encoding="utf-8",
        )
        print(f"  -> claims={len(claims)} answer-packet={out}")

    report = ddl.render_check_work_report(
        batch_label=f"Claude batch offset {args.offset}",
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
