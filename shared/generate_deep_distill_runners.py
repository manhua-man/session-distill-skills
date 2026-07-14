#!/usr/bin/env python3
"""Generate platform deep-distill-run.py wrappers from shared template."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PLATFORMS = {
    "hermes": {
        "title": "Hermes",
        "script": "hermes-session-distill.py",
        "mod_name": "hermes_sd",
        "platform": "hermes",
        "project_fields": "meta.get('project_path') or meta.get('cwd') or ''",
        "filter_field": "project_path",
    },
    "antigravity": {
        "title": "Antigravity",
        "script": "antigravity-session-distill.py",
        "mod_name": "agy_sd",
        "platform": "antigravity",
        "project_fields": "meta.get('project_path') or ''",
        "filter_field": "project_path",
    },
    "opencode": {
        "title": "OpenCode",
        "script": "opencode-session-distill.py",
        "mod_name": "opencode_sd",
        "platform": "opencode",
        "project_fields": "meta.get('project_path') or ''",
        "filter_field": "project_path",
    },
}

TEMPLATE = '''#!/usr/bin/env python3
"""{title} Deep Distill batch runner (shared paradigm)."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import deep_distill_lib as ddl

SCRIPT = Path(__file__).resolve().parent / "{script}"
spec = importlib.util.spec_from_file_location("{mod_name}", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

QUEUE_FILE = mod.DISTILL_DIR / "servers-deep-queue.md"
ANSWER_DIR = mod.DISTILL_DIR / "distilled" / "answer-packets"
CHECK_WORK_DIR = mod.DISTILL_DIR / "distilled" / "check-work"


def load_servers_sessions() -> list[dict]:
    manifest = mod.load_manifest()
    sessions = [
        s for s in manifest.get("sessions", [])
        if "servers" in ({project_fields}).lower()
    ]
    return sorted(sessions, key=lambda s: s.get("timestamp") or s.get("last_write_time") or "")


def session_index(sessions: list[dict]) -> dict[str, dict]:
    return {{s["session_id"]: s for s in sessions}}


def main() -> int:
    parser = argparse.ArgumentParser(description="{title} deep distill batch runner")
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
    print(f"==> {title} deep distill batch: {{len(batch)}} sessions (offset={{args.offset}})")
    for s in batch:
        print(f"  - {{s['session_id']}} {{(s.get('thread_name') or '')[:60]}}")

    if args.force_bundle:
        mod.cmd_bundle(next_count=0, force=True, session_ids=ids)

    for meta in batch:
        sid = meta["session_id"]
        path = mod.PACKETS_DIR / f"{{sid}}.md"
        if not path.exists():
            print(f"missing packet: {{path}}")
            continue
        packet_text = path.read_text(encoding="utf-8", errors="replace")
        claims = ddl.extract_claims(packet_text, meta)
        questions = ddl.default_questions(claims)
        out = ANSWER_DIR / f"{{sid}}.md"
        out.write_text(
            ddl.render_answer_packet(
                sid, meta, claims, questions,
                platform="{platform}",
                project_path={project_fields},
            ),
            encoding="utf-8",
        )
        print(f"  -> claims={{len(claims)}} answer-packet={{out}}")

    report = ddl.render_check_work_report(
        batch_label=f"{title} batch offset {{args.offset}}",
        session_ids=ids,
        promoted=[],
        not_promoted=[],
        verdict="PENDING",
    )
    report_path = CHECK_WORK_DIR / f"batch-offset-{{args.offset}}-report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"==> check-work stub: {{report_path}}")
    print("==> Next: answer-me verify each Q → promote ANSWERED only → update check-work → mark distilled")
    print(f"==> Queue file: {{QUEUE_FILE}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def main() -> int:
    for name, cfg in PLATFORMS.items():
        pkg = ROOT / f"{name}-session-distill" / "bin" / "deep-distill-run.py"
        pkg.parent.mkdir(parents=True, exist_ok=True)
        pkg.write_text(TEMPLATE.format(**cfg), encoding="utf-8")
        print(f"wrote {pkg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
