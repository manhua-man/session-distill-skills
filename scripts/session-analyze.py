#!/usr/bin/env python3
"""Cross-platform session analysis, semantic clustering, DB inspection, and cleanup tool."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Supported platform adapters
_PLATFORMS = [
    "cursor",
    "claude",
    "codex",
    "grok",
    "hermes",
    "antigravity",
    "opencode",
]


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
    return str(
        session.get("workspace")
        or session.get("project_path")
        or session.get("projectPath")
        or session.get("cwd")
        or ""
    ).strip()


# ---------------------------------------------------------------------------
# Semantic Categorizer
# ---------------------------------------------------------------------------

CATEGORIES = [
    (
        "Payment & Commerce",
        ["pay", "支付", "退款", "refund", "order", "订单", "wxpay", "alipay", "商户", "mch", "out_trade_no", "certificate", "公钥", "证书"],
    ),
    (
        "Auth & User & SMS",
        ["auth", "login", "登录", "sms", "短信", "token", "jwt", "session", "user", "用户", "uos", "persona", "account", "账号", "captcha", "验证码"],
    ),
    (
        "Activity & Gameplay & Config",
        ["activity", "活动", "boss", "task", "任务", "sign", "签到", "config", "配置", "wings", "翅膀", "pvp", "gameplay", "reward", "奖励"],
    ),
    (
        "Database & Migration",
        ["migration", "迁移", "index", "索引", "db", "database", "sql", "typeorm", "postgres", "table", "表", "drop", "alter"],
    ),
    (
        "Deployment & Ops & Infra",
        ["deploy", "部署", "server", "服务器", "nginx", "redis", "ops", "运维", "monitor", "监控", "disk", "磁盘", "docker", "compose", "backup", "备份"],
    ),
    (
        "Multi-Product Architecture",
        ["kousuan", "口算", "cross-product", "多产品", "warrior", "勇士", "tuya", "涂鸦", "monorepo", "shared", "在中台", "解耦"],
    ),
    (
        "Git & Code Review",
        ["git", "commit", "push", "review", "审查", "branch", "分支", "pr", "patch", "diff", "merge", "linus"],
    ),
]


def classify_session_text(text: str) -> str:
    text_lower = text.lower()
    for cat_name, keywords in CATEGORIES:
        if any(kw in text_lower for kw in keywords):
            return cat_name
    return "General & Development"


# ---------------------------------------------------------------------------
# Session Scanner
# ---------------------------------------------------------------------------

def scan_platform_sessions(
    platform: str,
    distill_dir: Path,
    manifest_name: str,
    project_filter: str = "",
    active_only: bool = False,
) -> list[dict[str, Any]]:
    if not distill_dir.exists():
        return []

    manifest_file = distill_dir / manifest_name
    manifest_map: dict[str, dict[str, Any]] = {}
    if manifest_file.exists():
        try:
            m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            for s in m_data.get("sessions", []):
                sid = s.get("session_id")
                if sid:
                    manifest_map[sid] = s
        except Exception:
            pass

    sessions: list[dict[str, Any]] = []
    revisions_dir = distill_dir / "revisions"
    answer_dir = distill_dir / "distilled" / "answer-packets"
    packets_dir = distill_dir / "packets"
    seen_sids: set[str] = set()

    # Process all sessions from manifest first
    for sid, meta in manifest_map.items():
        ws = _extract_workspace(meta)
        if project_filter and project_filter.lower() not in ws.lower():
            continue

        seen_sids.add(sid)
        name = meta.get("name") or meta.get("thread_name") or "Untitled"
        status = meta.get("status", "unknown")

        user_msgs: list[str] = []
        asst_msgs: list[str] = []
        turn_count = 0

        # Try to read chunks if revision exists
        rev_chunk_files = list(revisions_dir.glob(f"{sid}/*/chunks/0001.json"))
        if rev_chunk_files:
            try:
                c_data = json.loads(rev_chunk_files[0].read_text(encoding="utf-8", errors="ignore"))
                turns = c_data.get("turns", [])
                turn_count = len(turns)
                for t in turns:
                    user_msgs.extend(t.get("user_messages", []))
                    asst_msgs.extend(t.get("assistant_updates", []))
            except Exception:
                pass

        # Try to read answer packet
        claims_count = 0
        ans_file = answer_dir / f"{sid}.md"
        ans_text = ""
        if ans_file.exists():
            try:
                ans_text = ans_file.read_text(encoding="utf-8", errors="ignore")
                claims_count = len(re.findall(r"^\d+\.\s+", ans_text, re.MULTILINE))
            except Exception:
                pass

        # Try packet.md if turns are empty
        if turn_count == 0:
            pkt_file = packets_dir / f"{sid}.md"
            if pkt_file.exists():
                try:
                    p_text = pkt_file.read_text(encoding="utf-8", errors="ignore")
                    turns_match = re.findall(r"###\s+Turn\s+\d+", p_text)
                    turn_count = len(turns_match) if turns_match else (1 if p_text.strip() else 0)
                except Exception:
                    pass

        is_active = (turn_count > 0 or claims_count > 0 or status == "distilled")
        if active_only and not is_active:
            continue

        u_text = "\n".join(user_msgs)
        a_text = "\n".join(asst_msgs)
        combined_text = f"{name}\n{u_text[:600]}\n{a_text[:600]}\n{ans_text[:600]}"

        sessions.append({
            "platform": platform,
            "session_id": sid,
            "name": name,
            "workspace": ws,
            "status": status,
            "turn_count": turn_count,
            "user_msg_count": len(user_msgs),
            "asst_msg_count": len(asst_msgs),
            "user_text": u_text,
            "asst_text": a_text,
            "claims_count": claims_count,
            "is_active": is_active,
            "category": classify_session_text(combined_text),
        })

    # Scan revision chunks for any sessions not listed in manifest
    if revisions_dir.exists():
        for chunk_file in revisions_dir.glob("*/*/chunks/0001.json"):
            sid = chunk_file.parents[2].name
            if sid in seen_sids:
                continue

            try:
                c_data = json.loads(chunk_file.read_text(encoding="utf-8", errors="ignore"))
                turns = c_data.get("turns", [])
                user_msgs = []
                asst_msgs = []
                for t in turns:
                    user_msgs.extend(t.get("user_messages", []))
                    asst_msgs.extend(t.get("assistant_updates", []))

                u_text = "\n".join(user_msgs)
                a_text = "\n".join(asst_msgs)
                meta = manifest_map.get(sid, {})
                ws = _extract_workspace(meta)
                if project_filter and project_filter.lower() not in ws.lower():
                    continue

                name = meta.get("name") or meta.get("thread_name") or "Untitled"
                claims_count = 0
                ans_file = answer_dir / f"{sid}.md"
                ans_text = ""
                if ans_file.exists():
                    ans_text = ans_file.read_text(encoding="utf-8", errors="ignore")
                    claims_count = len(re.findall(r"^\d+\.\s+", ans_text, re.MULTILINE))

                is_active = (len(turns) > 0 or claims_count > 0)
                if active_only and not is_active:
                    continue

                sessions.append({
                    "platform": platform,
                    "session_id": sid,
                    "name": name,
                    "workspace": ws,
                    "status": meta.get("status", "unknown"),
                    "turn_count": len(turns),
                    "user_msg_count": len(user_msgs),
                    "asst_msg_count": len(asst_msgs),
                    "user_text": u_text,
                    "asst_text": a_text,
                    "claims_count": claims_count,
                    "is_active": is_active,
                    "category": classify_session_text(f"{name}\n{u_text[:600]}\n{a_text[:600]}\n{ans_text[:600]}"),
                })
                seen_sids.add(sid)
            except Exception:
                pass

    return sessions


# ---------------------------------------------------------------------------
# Database & Storage Inspection
# ---------------------------------------------------------------------------

def inspect_cursor_storage() -> dict[str, Any]:
    home = Path.home()
    db_path = home / "AppData" / "Roaming" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    ws_storage = home / "AppData" / "Roaming" / "Cursor" / "User" / "workspaceStorage"

    result: dict[str, Any] = {
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "workspace_storage_exists": ws_storage.exists(),
        "workspaces_mapped": 0,
        "composer_headers_count": 0,
        "disk_kv_keys_count": 0,
        "key_prefixes": {},
        "workspace_distribution": Counter(),
    }

    if not db_path.exists():
        return result

    # 1. Map workspaceStorage
    ws_map: dict[str, str] = {}
    if ws_storage.exists():
        for d in ws_storage.iterdir():
            if not d.is_dir():
                continue
            ws_json = d / "workspace.json"
            if ws_json.exists():
                try:
                    data = json.loads(ws_json.read_text("utf-8"))
                    folder = data.get("folder", "")
                    if folder:
                        if folder.startswith("file:///"):
                            parsed = urllib.parse.unquote(folder[8:])
                            if len(parsed) >= 2 and parsed[1] == ":":
                                parsed = parsed.replace("/", "\\")
                            folder = parsed
                        ws_map[d.name] = folder
                except Exception:
                    pass
    result["workspaces_mapped"] = len(ws_map)

    # 2. Inspect SQLite
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
        cur = conn.cursor()

        # Count composer headers
        try:
            cur.execute("SELECT workspaceId, count(*) FROM composerHeaders GROUP BY workspaceId")
            for wid, cnt in cur.fetchall():
                ws_path = ws_map.get(wid, wid or "(empty)")
                result["workspace_distribution"][ws_path] += cnt
                result["composer_headers_count"] += cnt
        except Exception:
            pass

        # Sample DiskKV prefixes
        try:
            cur.execute("SELECT substr(key, 1, 15), count(*) FROM cursorDiskKV GROUP BY substr(key, 1, 15)")
            for prefix, cnt in cur.fetchall():
                result["key_prefixes"][prefix] = cnt
                result["disk_kv_keys_count"] += cnt
        except Exception:
            pass

        conn.close()
    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# Clean Processed
# ---------------------------------------------------------------------------

def clean_processed_sessions(
    platform: str,
    distill_dir: Path,
    manifest_name: str,
    project_filter: str,
    execute: bool = False,
) -> dict[str, Any]:
    result = {
        "platform": platform,
        "freed_bytes": 0,
        "files_pruned": 0,
        "records_pruned": 0,
    }
    if not distill_dir.exists() or not project_filter:
        return result

    manifest_file = distill_dir / manifest_name
    if not manifest_file.exists():
        return result

    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        sessions = data.get("sessions", [])
        retained = []
        for s in sessions:
            ws = _extract_workspace(s)
            is_match = project_filter.lower() in ws.lower()
            is_distilled = s.get("status") in {"distilled", "skipped"}
            if is_match and is_distilled:
                result["records_pruned"] += 1
                sid = s.get("session_id")
                rev_dir = distill_dir / "revisions" / sid
                if rev_dir.exists():
                    for f in rev_dir.glob("**/*"):
                        if f.is_file():
                            result["freed_bytes"] += f.stat().st_size
                            result["files_pruned"] += 1
                            if execute:
                                try:
                                    f.unlink()
                                except Exception:
                                    pass
                    if execute:
                        import shutil
                        try:
                            shutil.rmtree(rev_dir)
                        except Exception:
                            pass
            else:
                retained.append(s)

        if execute and result["records_pruned"] > 0:
            data["sessions"] = retained
            data["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            manifest_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# CLI & Output Formatting
# ---------------------------------------------------------------------------

def format_report(sessions: list[dict[str, Any]], project_filter: str = "") -> str:
    total_sessions = len(sessions)
    active_sessions = sum(1 for s in sessions if s.get("is_active"))
    empty_drafts = total_sessions - active_sessions
    total_turns = sum(s["turn_count"] for s in sessions)
    total_claims = sum(s["claims_count"] for s in sessions)

    categories = defaultdict(list)
    for s in sessions:
        categories[s["category"]].append(s)

    lines = [
        "=" * 85,
        f"       SESSION SEMANTIC ANALYSIS REPORT [Filter: '{project_filter or 'ALL'}']",
        "=" * 85,
        f"Total Sessions Analyzed:  {total_sessions:<6} (Active: {active_sessions}, Empty Drafts: {empty_drafts})",
        f"Total Conversation Turns: {total_turns}",
        f"Total Extracted Claims:   {total_claims}",
        "-" * 85,
        f"{'Category':<32} {'Sessions':<10} {'Turns':<10} {'Claims':<10} {'% Share':<8}",
        "-" * 85,
    ]

    for cat_name, items in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True):
        cat_turns = sum(s["turn_count"] for s in items)
        cat_claims = sum(s["claims_count"] for s in items)
        share = (len(items) / total_sessions * 100) if total_sessions else 0
        lines.append(
            f"{cat_name:<32} {len(items):<10} {cat_turns:<10} {cat_claims:<10} {share:>5.1f}%"
        )

    lines.extend([
        "-" * 85,
        "",
        "### Top 10 Most Active Sessions by Turn Count:",
        "",
    ])

    sorted_by_turns = sorted(sessions, key=lambda s: s["turn_count"], reverse=True)[:10]
    for idx, s in enumerate(sorted_by_turns, 1):
        name_trunc = s['name'][:42]
        lines.append(
            f"  {idx:2d}. [{s['session_id'][:8]}] {name_trunc:<44} "
            f"Turns: {s['turn_count']:3d} | Category: {s['category']}"
        )

    lines.append("=" * 85)
    return "\n".join(lines)


def self_test() -> None:
    # Test classifier
    assert classify_session_text("微信支付回调验签") == "Payment & Commerce"
    assert classify_session_text("SMS login code timeout") == "Auth & User & SMS"
    assert classify_session_text("World boss activity config") == "Activity & Gameplay & Config"
    assert classify_session_text("TypeORM migration and indexes") == "Database & Migration"
    assert classify_session_text("Nginx docker compose deploy") == "Deployment & Ops & Infra"
    assert classify_session_text("Kousuan vs word warrior monorepo") == "Multi-Product Architecture"
    assert classify_session_text("Git commit and push") == "Git & Code Review"
    assert _extract_workspace({"project_path": "e:\\project\\servers"}) == "e:\\project\\servers"
    print("session-analyze self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser(description="Session semantic analysis, DB inspection, and cleanup tool")
    parser.add_argument("--project", default="", help="Filter by project/workspace name (e.g. servers)")
    parser.add_argument("--platform", default="", help="Filter by platform (e.g. cursor, codex, grok)")
    parser.add_argument("--active-only", action="store_true", help="Include only active interactive sessions (skip empty drafts)")
    parser.add_argument("--inspect-db", action="store_true", help="Inspect Cursor SQLite physical schema and namespaces")
    parser.add_argument("--clean-processed", action="store_true", help="Prune processed raw files and manifest stubs")
    parser.add_argument("--execute", action="store_true", help="Apply cleanup actions (default is dry-run)")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("command", nargs="?", default="", help="Optional sub-command (self-test)")

    args = parser.parse_args()

    if args.command == "self-test":
        self_test()
        return 0

    if args.inspect_db:
        info = inspect_cursor_storage()
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            print("=" * 75)
            print("                   CURSOR SQLITE & STORAGE INSPECTION")
            print("=" * 75)
            print(f"Database Path:          {info['db_path']}")
            print(f"Database Exists:        {info['db_exists']}")
            print(f"Mapped Workspaces:      {info['workspaces_mapped']}")
            print(f"Total Composer Headers: {info['composer_headers_count']}")
            print(f"Total DiskKV Keys:      {info['disk_kv_keys_count']}")
            print("-" * 75)
            print("Top Workspaces in SQLite:")
            for ws, cnt in info["workspace_distribution"].most_common(10):
                print(f"  [{cnt:4d} sessions] {ws}")
            print("-" * 75)
            print("DiskKV Key Prefix Distribution:")
            for prefix, cnt in sorted(info["key_prefixes"].items(), key=lambda x: x[1], reverse=True)[:10]:
                print(f"  {prefix:<20} {cnt:>8d} rows")
            print("=" * 75)
        return 0

    distill_map = get_distill_dirs()
    target_platforms = [args.platform] if args.platform else _PLATFORMS

    if args.clean_processed:
        if not args.project:
            print("Error: --clean-processed requires --project <name> to avoid accidental bulk deletion.")
            return 1
        print(f"==> Clean Processed: {'EXECUTING' if args.execute else 'DRY RUN'} (Project: {args.project})")
        total_freed = 0
        total_files = 0
        total_records = 0
        for p in target_platforms:
            if p not in distill_map:
                continue
            d_dir, m_name = distill_map[p]
            res = clean_processed_sessions(p, d_dir, m_name, args.project, execute=args.execute)
            total_freed += res["freed_bytes"]
            total_files += res["files_pruned"]
            total_records += res["records_pruned"]
            print(
                f"  [{p:<11}] pruned {res['records_pruned']:3d} records, "
                f"{res['files_pruned']:3d} files ({res['freed_bytes'] / (1024*1024):.2f} MB)"
            )
        print(
            f"==> Total: pruned {total_records} records, {total_files} files "
            f"({total_freed / (1024*1024):.2f} MB freed)"
        )
        if not args.execute:
            print("Tip: Add --execute to apply the deletion.")
        return 0

    all_sessions = []
    for p in target_platforms:
        if p not in distill_map:
            continue
        d_dir, m_name = distill_map[p]
        all_sessions.extend(
            scan_platform_sessions(
                p,
                d_dir,
                m_name,
                project_filter=args.project,
                active_only=args.active_only,
            )
        )

    if args.json:
        print(json.dumps(all_sessions, ensure_ascii=False, indent=2))
    else:
        print(format_report(all_sessions, project_filter=args.project))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
