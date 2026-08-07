#!/usr/bin/env python3
"""Cross-platform distillation status dashboard for session-distill-skills."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def get_distill_dirs() -> dict[str, tuple[Path, str]]:
    home = Path.home()
    appdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))

    return {
        "cursor": (
            Path(os.environ.get("CURSOR_DISTILL_DIR", home / ".cursor" / "session-distill")),
            "cursor-manifest.json",
        ),
        "claude": (
            Path(os.environ.get("CLAUDE_DISTILL_DIR", home / ".claude" / "session-distill")),
            "manifest.json",
        ),
        "codex": (
            Path(os.environ.get("CODEX_DISTILL_DIR", Path(os.environ.get("CODEX_HOME", home / ".codex")) / "session-distill")),
            "manifest.json",
        ),
        "grok": (
            Path(os.environ.get("GROK_DISTILL_DIR", Path(os.environ.get("GROK_HOME", home / ".grok")) / "session-distill")),
            "manifest.json",
        ),
        "hermes": (
            Path(os.environ.get("HERMES_DISTILL_DIR", Path(os.environ.get("HERMES_HOME", appdata / "hermes")) / "session-distill")),
            "manifest.json",
        ),
        "antigravity": (
            Path(os.environ.get("AGY_DISTILL_DIR", home / ".gemini" / "antigravity-cli" / "session-distill")),
            "manifest.json",
        ),
        "opencode": (
            Path(os.environ.get("OPENCODE_DISTILL_DIR", home / ".local" / "share" / "opencode" / "session-distill")),
            "manifest.json",
        ),
    }


def get_platform_stats(platform: str, distill_dir: Path, manifest_name: str) -> dict:
    stats = {
        "platform": platform,
        "distill_dir": str(distill_dir),
        "exists": distill_dir.exists(),
        "total_sessions": 0,
        "new": 0,
        "bundled": 0,
        "distilled": 0,
        "pending_redistill": 0,
        "skipped": 0,
        "packets_count": 0,
        "answers_count": 0,
        "sessions_count": 0,
        "last_updated": "-",
    }

    if not distill_dir.exists():
        return stats

    manifest_file = distill_dir / manifest_name
    if manifest_file.exists():
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            sessions = data.get("sessions", [])
            stats["total_sessions"] = len(sessions)
            stats["last_updated"] = data.get("updated_at", "-")
            for s in sessions:
                st = s.get("status", "new")
                if st in stats:
                    stats[st] += 1
                else:
                    stats["new"] += 1
        except Exception:
            pass

    packets_dir = distill_dir / "packets"
    if packets_dir.exists():
        stats["packets_count"] = len(list(packets_dir.glob("*.md")))

    answers_dir = distill_dir / "distilled" / "answer-packets"
    if answers_dir.exists():
        stats["answers_count"] = len(list(answers_dir.glob("*.md")))

    sessions_dir = distill_dir / "distilled" / "sessions"
    if sessions_dir.exists():
        stats["sessions_count"] = len(list(sessions_dir.glob("*.md")))

    return stats


def print_dashboard(format_md: bool = False) -> None:
    platforms = get_distill_dirs()
    all_stats = []

    for name, (ddir, mname) in platforms.items():
        all_stats.append(get_platform_stats(name, ddir, mname))

    if format_md:
        print("# Session Distill Cross-Platform Status Dashboard\n")
        print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
        print("| Platform | Sessions | Packets | Answers | Session Notes | Distilled | Pending | Dir Exists |")
        print("|----------|----------|---------|---------|---------------|-----------|---------|------------|")
        for s in all_stats:
            exists_str = "Yes" if s["exists"] else "No"
            print(
                f"| **{s['platform']}** | {s['total_sessions']} | {s['packets_count']} | "
                f"{s['answers_count']} | {s['sessions_count']} | {s['distilled']} | "
                f"{s['pending_redistill']} | {exists_str} |"
            )
    else:
        print("=" * 85)
        print(" SESSION DISTILL CROSS-PLATFORM STATUS DASHBOARD".center(85))
        print("=" * 85)
        header = f"{'Platform':<12} {'Total':<7} {'Packets':<9} {'Answers':<9} {'Notes':<7} {'Distilled':<10} {'Pending':<8} {'Exists':<7}"
        print(header)
        print("-" * 85)
        for s in all_stats:
            exists_str = "YES" if s["exists"] else "NO"
            print(
                f"{s['platform']:<12} {s['total_sessions']:<7} {s['packets_count']:<9} "
                f"{s['answers_count']:<9} {s['sessions_count']:<7} {s['distilled']:<10} "
                f"{s['pending_redistill']:<8} {exists_str:<7}"
            )
        print("=" * 85)


def main():
    format_md = "--md" in sys.argv or "--markdown" in sys.argv
    print_dashboard(format_md=format_md)


if __name__ == "__main__":
    main()
