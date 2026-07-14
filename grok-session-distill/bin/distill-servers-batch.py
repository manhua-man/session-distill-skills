#!/usr/bin/env python3
"""DEPRECATED — use deep-distill-run.py + answer-me + check-work instead.

This script auto-promotes without toolchain verification. Kept only for legacy index rebuilds.
"""

from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "grok-session-distill.py"
spec = importlib.util.spec_from_file_location("grok_sd", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PACKETS_DIR = mod.PACKETS_DIR
DISTILLED_DIR = mod.DISTILLED_DIR
KNOWLEDGE_FILE = mod.KNOWLEDGE_FILE
MANIFEST_FILE = mod.MANIFEST_FILE

THEME_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("生产部署", ("deploy", "deployment", "生产", "production", "发版", "rollback", "migration")),
    ("本地 Docker / 联调", ("docker", "ngrok", "内网穿透", "local dev", "13001", "test stack", "ops frontend")),
    ("认证 / UOS / 登录", ("auth", "uos", "login", "logout", "passport", "登录", "会话")),
    ("活动模块", ("activity", "活动", "sign-in", "签到", "claimtask", "taskreward")),
    ("支付 / 退款 / 订单", ("payment", "refund", "order", "退款", "alipay", "wechat")),
    ("华为归因 / 推广", ("huawei", "华为", "attribution", "promotion", "oaId")),
    ("文档 / AI 入口治理", ("update-docs", "revise-ai-docs", "AGENTS", "CLAUDE", "documentation", "文档")),
    ("代码审查 / 提交", ("code review", "commit", "push", "git", "linus", "审查", "提交")),
    ("运维 / 健康检查", ("health", "monitor", "status", "performance", "运行状态", "生产库")),
    ("会话蒸馏 / AI 工具链", ("session-distill", "distill", "grok", "codex", "cursor", "mcp", "skill")),
]


def load_servers_sessions() -> list[dict]:
    manifest = mod.load_manifest()
    return [
        s for s in manifest.get("sessions", [])
        if "servers" in (s.get("project_path") or "").lower()
    ]


def parse_packet(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    def grab(field: str) -> str:
        match = re.search(rf"- {re.escape(field)}: `([^`]*)`", text)
        return match.group(1).strip() if match else ""

    coverage = "partial" if "Coverage: `partial`" in text else "high"
    warnings = re.findall(r"^- (.+)$", "\n".join(
        line for line in text.splitlines() if line.startswith("- ") and "clipped" in line.lower()
    ), re.MULTILINE)

    user_blocks = re.findall(r"### User Requests\s+```text\s+(.*?)\s+```", text, re.DOTALL)
    command_lines: list[str] = []
    for match in re.finditer(r"### Commands\s+(.*?)(?=\n### |\n## Turn |\n## Suggested|\Z)", text, re.DOTALL):
        for line in match.group(1).splitlines():
            if line.startswith("- `") and line.rstrip().endswith("`"):
                command_lines.append(line[3:].strip().strip("`"))

    file_refs = re.findall(r"^- `([^`]+)` \((\d+)\)", "\n".join(
        line for line in text.splitlines() if line.startswith("- `") and "Referenced Files" in text[:text.find(line) if line in text else 0]
    ))
    ref_section = re.search(r"## Referenced Files\s+(.*?)(?:\n## |\Z)", text, re.DOTALL)
    refs: list[tuple[str, int]] = []
    if ref_section:
        for line in ref_section.group(1).splitlines():
            match = re.match(r"^- `([^`]+)` \((\d+)\)", line.strip())
            if match:
                refs.append((match.group(1), int(match.group(2))))

    return {
        "title": grab("Title"),
        "coverage": coverage,
        "git_commit": grab("Git commit"),
        "created": grab("Created"),
        "warnings": warnings,
        "user_requests": [b.strip() for b in user_blocks if b.strip()],
        "commands": command_lines[:40],
        "file_refs": refs[:20],
        "bytes": path.stat().st_size,
    }


def classify_theme(title: str, users: list[str]) -> str:
    blob = f"{title}\n" + "\n".join(users).lower()
    for theme, keys in THEME_RULES:
        if any(k.lower() in blob for k in keys):
            return theme
    return "其他"


def write_session_note(session_id: str, meta: dict, parsed: dict, theme: str) -> None:
    note_path = DISTILLED_DIR / f"{session_id}.md"
    users = parsed["user_requests"][:5]
    commands = parsed["commands"][:15]
    refs = parsed["file_refs"][:10]
    lines = [
        f"# Session Distillation: {session_id}",
        "",
        "## Metadata",
        "",
        f"- Title: {meta.get('thread_name') or parsed['title']}",
        f"- Theme: {theme}",
        f"- Coverage: {parsed['coverage']}",
        f"- Packet bytes: {parsed['bytes']}",
        f"- Git commit: {parsed['git_commit'] or meta.get('cwd', '')}",
        "",
        "## Summary",
        "",
        f"- Primary intent: {meta.get('thread_name') or parsed['title'] or 'unknown'}",
    ]
    if users:
        lines.append("- User requests:")
        lines.extend(f"  - {u[:500]}" for u in users)
    if commands:
        lines.append("- Notable commands/tools:")
        lines.extend(f"  - {c}" for c in commands)
    if refs:
        lines.append("- Top referenced paths:")
        lines.extend(f"  - `{r}` ({c})" for r, c in refs)

    lines.extend([
        "",
        "## Raw Review",
        "",
        "Reviewed regenerated packet with higher clip limits (TEXT/OUTPUT 32000).",
        f"chat_history.jsonl: `{meta.get('file_path', '')}`",
    ])
    if parsed["coverage"] == "partial":
        lines.append("- Partial coverage: inspect raw JSONL before promoting task-specific facts.")

    lines.extend([
        "",
        "## Promotion Decision",
        "",
        "No Promotion for this session note.",
        "Stable cross-session patterns are aggregated in `knowledge-base.md` (servers batch).",
        "",
    ])
    note_path.write_text("\n".join(lines), encoding="utf-8")


def build_knowledge_base(theme_sessions: dict[str, list[tuple[str, dict, dict]]]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "# Archived Session Knowledge Base",
        "",
        f"## Servers Grok Batch ({now})",
        "",
        "Distilled from 86 `E:\\project\\servers` Grok sessions. Packets regenerated with",
        "TEXT_LIMIT/OUTPUT_LIMIT=32000 before review. Session notes record per-chat context;",
        "this section keeps only stable, reusable workflows.",
        "",
    ]

    stable_entries = [
        (
            "生产部署",
            "When planning production deploy for this repo, read `.claude/skills/game-server-production-deploy/SKILL.md` "
            "and scripts under `scripts/windows/deployment/`; verify health at `/api/v1/health` after Nest recreate. "
            "Prefer control-plane updates (game config / activity rules / switches) when code migrations are not required.",
            "019f37e8-33ec-7b22-831d-fba7f7533125",
        ),
        (
            "本地 Docker 联调",
            "Default local test stack: `docker-compose.test.yml`, API `http://localhost:13001`, DB port 5643, Redis 6480. "
            "Use ngrok against 13001 for client/payment callbacks; keep `test.env` callback domains aligned with the active tunnel.",
            "019ef397-a822-7be2-bdbe-7070e2cf08c4",
        ),
        (
            "认证 / UOS",
            "Auth/UOS work spans `packages/nestjs-server/src/modules/auth/` and client联调 docs under "
            "`docs/04-开发指南/UOS与游戏服对接/`. Prefer UOS user API identity over client displayName; "
            "verify `/api/v1/auth/uos/login` and membership endpoints together when refactoring login.",
            "019f56eb-cfff-7072-b919-37bdd0af5993",
        ),
        (
            "活动模块",
            "Activity debugging should start from admin activity APIs and `activity-engine.service.ts`, then confirm "
            "DB/runtime state on production only when the task explicitly needs live data. Unity ClaimTaskReward 500s "
            "require correlating server logs, activity config, and player state.",
            "019f44b6-43b0-7a42-a271-ea5d9c062520",
        ),
        (
            "支付 / 退款",
            "Payment/refund triage: check channel state first (WeChat/Alipay), then local order rows. "
            "Use repo skills/scripts for external refund sync; do not hand-write refund SQL.",
            "019ef37a-c8a3-7e53-8f10-da27bffd259e",
        ),
        (
            "文档 / AI 入口",
            "Human docs live in `docs/`; AI truth stays in `AGENTS.md` + `CLAUDE.md` + steering. "
            "Use `/update-docs` for human doc sync and `/revise-ai-docs` for AI entry maintenance—avoid duplicating long tables across both.",
            "019f224c-cb08-7360-8385-286798c8fb2c",
        ),
        (
            "代码审查 / Git",
            "Before push, split unrelated changes into logical commits; run targeted Jest via `findRelatedTests` for touched TS. "
            "Use `/code-review-linus` or `/review` for pre-land architecture checks on large diffs.",
            "019ef947-1f75-7030-aeb4-90e4707cfd28",
        ),
        (
            "运维 / 健康检查",
            "Production host `114.55.236.170`; inspect Nest container health and Postgres via documented SSH/docker exec paths. "
            "Distinguish local test stack ports from production when answering environment questions.",
            "019f4536-09c9-7242-84ac-2105d8b938ea",
        ),
        (
            "会话蒸馏",
            "Grok sessions live under `~/.grok/sessions/<project>/<id>/chat_history.jsonl`; packets are summaries only. "
            "If `Coverage: partial`, read raw JSONL before promotion. Keep raw files unless `--delete-raw` is explicit.",
            "019f5a00-00cd-7850-806e-56fc56494a5c",
        ),
    ]

    for section, text, source_id in stable_entries:
        lines.append(f"### {section}")
        lines.append("")
        lines.append(f"- `{section}`: {text} Source: `{source_id}`.")
        lines.append("")

    lines.append("## Theme Index (86 sessions)")
    lines.append("")
    for theme, items in sorted(theme_sessions.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"### {theme} ({len(items)})")
        lines.append("")
        for session_id, meta, _parsed in items[:12]:
            title = meta.get("thread_name") or _parsed.get("title") or session_id
            lines.append(f"- `{session_id}`: {title}")
        if len(items) > 12:
            lines.append(f"- ... and {len(items) - 12} more")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    mod.ensure_dirs()
    sessions = load_servers_sessions()
    theme_sessions: dict[str, list[tuple[str, dict, dict]]] = defaultdict(list)
    marked = 0
    for meta in sessions:
        session_id = meta["session_id"]
        packet = PACKETS_DIR / f"{session_id}.md"
        if not packet.exists():
            print(f"missing packet: {session_id}")
            continue
        parsed = parse_packet(packet)
        theme = classify_theme(meta.get("thread_name") or parsed["title"], parsed["user_requests"])
        theme_sessions[theme].append((session_id, meta, parsed))
        write_session_note(session_id, meta, parsed, theme)
        if mod.cmd_mark(session_id, "distilled") != 0:
            print(f"mark failed: {session_id}")
            continue
        marked += 1
    KNOWLEDGE_FILE.write_text(build_knowledge_base(theme_sessions), encoding="utf-8")
    print(f"==> Distilled {marked}/{len(sessions)} servers sessions")
    print(f"==> Knowledge base: {KNOWLEDGE_FILE}")
    mod.cmd_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())