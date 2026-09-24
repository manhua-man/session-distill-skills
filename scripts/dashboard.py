#!/usr/bin/env python3
"""Cross-platform distillation status dashboard for session-distill-skills."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def _extract_workspace(session: dict[str, Any]) -> str:
    ws = (
        session.get("workspace")
        or session.get("project_path")
        or session.get("projectPath")
        or session.get("cwd")
        or ""
    )
    return str(ws).strip()


def get_platform_stats(
    platform: str,
    distill_dir: Path,
    manifest_name: str,
    project_filter: str = "",
) -> dict[str, Any]:
    stats: dict[str, Any] = {
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
        "workspaces": Counter(),
    }

    if not distill_dir.exists():
        return stats

    manifest_file = distill_dir / manifest_name
    matching_sids: set[str] = set()

    if manifest_file.exists():
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            raw_sessions = data.get("sessions", [])
            stats["last_updated"] = data.get("updated_at", "-")

            for s in raw_sessions:
                ws = _extract_workspace(s)
                norm_ws = ws or "(unspecified)"
                stats["workspaces"][norm_ws] += 1

                if project_filter and project_filter.lower() not in ws.lower():
                    continue

                sid = s.get("session_id") or ""
                if sid:
                    matching_sids.add(sid)

                stats["total_sessions"] += 1
                st = s.get("status", "new")
                if st in stats:
                    stats[st] += 1
                else:
                    stats["new"] += 1
        except Exception:
            pass

    packets_dir = distill_dir / "packets"
    if packets_dir.exists():
        if project_filter:
            stats["packets_count"] = sum(
                1 for p in packets_dir.glob("*.md")
                if any(sid in p.name for sid in matching_sids)
            )
        else:
            stats["packets_count"] = len(list(packets_dir.glob("*.md")))

    answers_dir = distill_dir / "distilled" / "answer-packets"
    if answers_dir.exists():
        if project_filter:
            stats["answers_count"] = sum(
                1 for p in answers_dir.glob("*.md")
                if p.stem in matching_sids
            )
        else:
            stats["answers_count"] = len(list(answers_dir.glob("*.md")))

    sessions_dir = distill_dir / "distilled" / "sessions"
    if sessions_dir.exists():
        if project_filter:
            stats["sessions_count"] = sum(
                1 for p in sessions_dir.glob("*.md")
                if p.stem in matching_sids
            )
        else:
            stats["sessions_count"] = len(list(sessions_dir.glob("*.md")))

    return stats


def print_dashboard(
    format_md: bool = False,
    project_filter: str = "",
    show_breakdown: bool = False,
) -> None:
    platforms = get_distill_dirs()
    all_stats = []

    for name, (ddir, mname) in platforms.items():
        all_stats.append(get_platform_stats(name, ddir, mname, project_filter=project_filter))

    filter_notice = f" [Project Filter: '{project_filter}']" if project_filter else ""

    if format_md:
        print(f"# Session Distill Cross-Platform Status Dashboard{filter_notice}\n")
        print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
        print("| Platform | Sessions | Packets | Answers | Session Notes | Distilled | Pending | Dir Exists |")
        print("|----------|----------|---------|---------|---------------|-----------|---------|------------|")
        for s in all_stats:
            exists_str = "Yes" if s["exists"] else "No"
            pending_count = s.get("new", 0) + s.get("bundled", 0) + s.get("pending_redistill", 0)
            print(
                f"| **{s['platform']}** | {s['total_sessions']} | {s['packets_count']} | "
                f"{s['answers_count']} | {s['sessions_count']} | {s['distilled']} | "
                f"{pending_count} | {exists_str} |"
            )

        if show_breakdown or not project_filter:
            print("\n## Workspace Distribution\n")
            print("| Platform | Workspace / Project Path | Sessions |")
            print("|----------|--------------------------|----------|")
            for s in all_stats:
                if not s["workspaces"]:
                    continue
                for ws, count in s["workspaces"].most_common():
                    print(f"| {s['platform']} | `{ws}` | {count} |")
    else:
        title = f" SESSION DISTILL STATUS DASHBOARD{filter_notice} "
        print("=" * 85)
        print(title.center(85))
        print("=" * 85)
        header = f"{'Platform':<12} {'Total':<7} {'Packets':<9} {'Answers':<9} {'Notes':<7} {'Distilled':<10} {'Pending':<8} {'Exists':<7}"
        print(header)
        print("-" * 85)
        for s in all_stats:
            exists_str = "YES" if s["exists"] else "NO"
            pending_count = s.get("new", 0) + s.get("bundled", 0) + s.get("pending_redistill", 0)
            print(
                f"{s['platform']:<12} {s['total_sessions']:<7} {s['packets_count']:<9} "
                f"{s['answers_count']:<9} {s['sessions_count']:<7} {s['distilled']:<10} "
                f"{pending_count:<8} {exists_str:<7}"
            )
        print("=" * 85)

        if show_breakdown or not project_filter:
            print("\n" + "-" * 85)
            print(" WORKSPACE BREAKDOWN ".center(85))
            print("-" * 85)
            for s in all_stats:
                if not s["workspaces"]:
                    continue
                print(f"[{s['platform']}] (Total: {sum(s['workspaces'].values())})")
                for ws, count in s["workspaces"].most_common():
                    print(f"  - {count:<4} {ws}")
            print("-" * 85)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-platform session distillation status dashboard.")
    parser.add_argument("--project", type=str, default="", help="Filter sessions by project or workspace substring")
    parser.add_argument("--md", "--markdown", dest="format_md", action="store_true", help="Format output as Markdown")
    parser.add_argument("--breakdown", action="store_true", help="Show detailed workspace breakdown")
    args = parser.parse_args()

    print_dashboard(
        format_md=args.format_md,
        project_filter=args.project,
        show_breakdown=args.breakdown,
    )


if __name__ == "__main__":
    main()
