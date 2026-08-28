#!/usr/bin/env python3
"""Shared Deep Distill helpers (Grok paradigm) for all session-distill runners."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

try:
    from distill_core.candidate_id import make_candidate_id, normalize_claim
    from distill_core.revision import PIPELINE_VERSION
except ImportError:  # pragma: no cover - thin adapters without distill_core on path
    PIPELINE_VERSION = "deep-distill-v2"

    def normalize_claim(claim: str) -> str:
        return " ".join((claim or "").strip().lower().split())

    def make_candidate_id(**kwargs: str) -> str:
        return "legacy"


def resolve_repo_kb_path(project_path: str = "") -> Path:
    """Resolve the target repository's session-knowledge-base.md dynamically by project path or current working directory."""
    base_dir = Path(project_path).resolve() if project_path else Path.cwd().resolve()
    candidates = [
        base_dir / "server" / "word-warrior" / "notes" / "session-knowledge-base.md",
        base_dir / ".cursor" / "notes" / "conversations" / "session-knowledge-base.md",
        base_dir / ".session-distill" / "session-knowledge-base.md",
        base_dir / "notes" / "session-knowledge-base.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


FINAL_SECTION = re.compile(r"### (?:Final Answers|Assistant Updates|结论|核心结论|排查结果)\s+(?:```(?:text)?\s+)?(.*?)(?=\n###|\n##|\Z)", re.DOTALL)
USER_QUERY = re.compile(r"(?:<user_query>|### User Requests\s+|### User Intent\s+)\s*(.*?)(?:</user_query>|\n###|\n##|\Z)", re.DOTALL | re.IGNORECASE)

ANSWER_STATUSES = frozenset({"ANSWERED", "PARTIAL", "UNANSWERED", "CONTRADICTED", "STALE", "NOT_APPLICABLE", "PENDING"})


def generate_compact_manifest(turns: list[dict[str, Any]], *, budget_tokens: int = 3000) -> str:
    """
    Generate a compact, token-bounded exchange manifest (≤budget_tokens, approx 12,000 chars)
    summarizing user intents, tool calls, and final answers per turn window.
    """
    max_chars = budget_tokens * 4
    lines = ["## Compact Exchange Manifest", ""]
    current_len = sum(len(l) for l in lines)

    for idx, turn in enumerate(turns, start=1):
        turn_lines = [f"### Turn {idx}"]
        if turn.get("timestamp"):
            turn_lines.append(f"- Timestamp: {turn['timestamp']}")

        user_msgs = turn.get("user_messages") or []
        if user_msgs:
            intent = " ".join(str(m).strip() for m in user_msgs)[:150]
            turn_lines.append(f"- User Intent: {intent}")

        tools = turn.get("commands") or []
        if tools:
            tool_names = []
            for t in tools:
                if isinstance(t, dict):
                    name = t.get("name") or t.get("tool") or "tool"
                    args = t.get("args") or {}
                    if isinstance(args, dict):
                        target = args.get("TargetFile") or args.get("AbsolutePath") or args.get("CommandLine") or ""
                        if target:
                            tool_names.append(f"{name}({str(target)[:60]})")
                        else:
                            tool_names.append(name)
                    else:
                        tool_names.append(name)
                elif isinstance(t, str):
                    tool_names.append(t[:40])
            if tool_names:
                turn_lines.append(f"- Tool Signatures: {', '.join(tool_names[:6])}")

        answers = turn.get("final_answers") or []
        if answers:
            ans_summary = " ".join(str(a).strip() for a in answers)[:200]
            turn_lines.append(f"- Assistant Summary: {ans_summary}")

        turn_lines.append("")
        block = "\n".join(turn_lines)
        if current_len + len(block) > max_chars:
            lines.append("... [manifest truncated due to 3k token budget]")
            break
        lines.append(block)
        current_len += len(block)

    return "\n".join(lines)


def generate_compact_manifest_from_packet(packet_text: str, *, budget_tokens: int = 3000) -> str:
    """Generate token-bounded compact exchange manifest (≤budget_tokens) from packet text."""
    max_chars = budget_tokens * 4
    lines = ["## Compact Exchange Manifest", ""]
    current_len = sum(len(l) for l in lines)

    queries = USER_QUERY.findall(packet_text)
    answers = FINAL_SECTION.findall(packet_text)

    turn_count = max(len(queries), len(answers))
    if turn_count == 0:
        return ""

    for idx in range(turn_count):
        turn_lines = [f"### Turn {idx + 1}"]
        if idx < len(queries):
            q_text = queries[idx].strip()[:150]
            if q_text:
                turn_lines.append(f"- User Intent: {q_text}")
        if idx < len(answers):
            a_text = answers[idx].strip()[:200]
            if a_text:
                clean_ans = " ".join(a_text.split())
                turn_lines.append(f"- Assistant Summary: {clean_ans}")
        turn_lines.append("")
        block = "\n".join(turn_lines)
        if current_len + len(block) > max_chars:
            lines.append("... [manifest truncated due to 3k token budget]")
            break
        lines.append(block)
        current_len += len(block)

    return "\n".join(lines)


def memory_draft_entry_spec(drafts_dir: Path, session_id: str, claim: str, revision_id: str | None = None) -> tuple[str, str]:
    """Return (candidate_id, path) for an idempotent memory draft file."""
    normalized = normalize_claim(claim)
    candidate_id = make_candidate_id(
        source_revision_id=revision_id or session_id,
        candidate_kind="memory_draft",
        normalized_claim=normalized,
        pipeline_version=PIPELINE_VERSION,
    )
    return candidate_id, str(drafts_dir / f"{candidate_id}.md")


def extract_claims(packet_text: str, meta: dict[str, Any]) -> list[str]:
    """Extract hypothesis claims from a packet (Final Answers, structured findings, and file refs)."""
    claims: list[str] = []
    title = (meta.get("thread_name") or meta.get("name") or "").strip()
    if title and title.lower() != "untitled":
        claims.append(f"Session topic: {title}")

    # 1. Extract concrete finding sentences with keywords
    finding_matches = re.findall(r'(?:结论|分析|修复|确认|实现|根因|规范|建议|方案|定位|排查)[：:]\s*([^\n\r]+)', packet_text)
    for fm in finding_matches:
        fm_clean = fm.strip().lstrip('-*# ')
        if len(fm_clean) > 15:
            claims.append(fm_clean[:400])

    # 2. Extract Final Answers & Assistant Updates sections
    for match in FINAL_SECTION.finditer(packet_text):
        body = match.group(1).strip()
        for line in body.splitlines():
            line = line.strip().lstrip('-*# ')
            if not line or line.startswith("[MODE:"):
                continue
            if line.startswith(("|", "```")):
                continue
            if len(line) > 20:
                claims.append(line[:500])
        if len(claims) <= 1 and body:
            claims.append(body[:800])

    # 3. Extract User Queries
    if len(claims) <= 1:
        for match in USER_QUERY.finditer(packet_text):
            query = match.group(1).strip()
            if len(query) > 15:
                claims.append(f"User intent: {query[:500]}")

    # dedupe preserve order
    seen: set[str] = set()
    deduped: list[str] = []
    for claim in claims:
        key = claim.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
    return deduped[:12]


def extract_claims_from_turns(turns: list[dict[str, Any]], meta: dict[str, Any]) -> list[str]:
    """Extract claims directly from lossless turn objects (chunk/raw path)."""
    claims: list[str] = []
    title = (meta.get("thread_name") or meta.get("name") or "").strip()
    if title and title.lower() not in {"", "untitled"}:
        claims.append(f"Session topic: {title}")

    for turn in turns:
        for answer in turn.get("final_answers") or []:
            text = str(answer).strip()
            if not text:
                continue
            for line in text.splitlines():
                line = line.strip()
                if len(line) > 20 and not line.startswith(("[MODE:", "#", "|")):
                    claims.append(line[:500])
            if len(text) > 20:
                claims.append(text[:800])
        for message in turn.get("user_messages") or []:
            text = str(message).strip()
            if not text:
                continue
            if len(text) > 15:
                claims.append(f"User intent: {text[:500]}")

    seen: set[str] = set()
    deduped: list[str] = []
    for claim in claims:
        key = claim.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
    return deduped[:12]


def infer_lens(claim: str) -> str:
    lower = claim.lower()
    if any(k in lower for k in ("deploy", "nginx", "docker", "hsts", "ops")):
        return "deploy"
    if any(k in lower for k in ("pay", "order", "settlement", "payment", "cps")):
        return "payment"
    if any(k in lower for k in ("auth", "jwt", "login", "user")):
        return "auth"
    if any(k in lower for k in ("activity", "活动", "claim")):
        return "activity"
    return "repo"


def default_questions(claims: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index, claim in enumerate(claims, start=1):
        rows.append(
            {
                "id": f"Q{index}",
                "lens": infer_lens(claim),
                "class": "DISCOVERABLE",
                "question": f"Is this still true in the current repo/runtime? {claim}",
                "status": "PENDING",
                "answer": "",
                "evidence": "",
            }
        )
    return rows


def render_answer_packet(
    session_id: str,
    meta: dict[str, Any],
    claims: list[str],
    questions: list[dict[str, str]],
    *,
    platform: str,
    project_path: str = "",
    manifest_text: str = "",
) -> str:
    title = meta.get("thread_name") or meta.get("name") or session_id
    project = project_path or meta.get("project_path") or meta.get("workspace") or meta.get("cwd") or ""
    revision_id = meta.get("current_revision_id") or meta.get("revision_id") or ""
    extract_mode = meta.get("extract_mode") or ""
    lines = [
        f"# Answer Packet: {session_id}",
        "",
        "## Scope",
        f"- Platform: {platform}",
        f"- Title: {title}",
        f"- Project: {project}",
    ]
    if revision_id:
        lines.append(f"- Revision: `{revision_id}`")
    if extract_mode:
        lines.append(f"- Extract mode: `{extract_mode}`")
    lines.extend([
        "- Phase: extract complete; **verify each Q with toolchain before promotion**",
        "",
    ])

    if manifest_text:
        lines.extend([manifest_text, ""])

    lines.extend([
        "## Claims extracted (hypotheses)",
        "",
    ])
    if claims:
        for index, claim in enumerate(claims, start=1):
            lines.append(f"{index}. {claim}")
    else:
        lines.append("1. (no claims extracted — read raw transcript and add manually)")

    lines.extend(["", "## Results", "", "| ID | Lens | Status | Answer | Evidence |", "| --- | --- | --- | --- | --- |"])
    for row in questions:
        lines.append(
            f"| {row['id']} | {row['lens']} | {row['status']} | {row['answer']} | {row['evidence']} |"
        )
    lines.extend(
        [
            "",
            "## Return to grill-me",
            "- Fill PARTIAL/UNANSWERED/CONTRADICTED here after verification.",
            "",
            "## Promotion gate",
            "- Only `ANSWERED` rows may update KB / docs / AGENTS / steering.",
            "- Chat/packet text alone is not evidence; attach toolchain proof in Evidence column.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def render_check_work_report(
    *,
    batch_label: str,
    session_ids: list[str],
    promoted: list[tuple[str, str, str]],
    not_promoted: list[tuple[str, str]],
    verdict: str = "PENDING",
) -> str:
    lines = [
        f"# Check-work: {batch_label}",
        "",
        f"Sessions: {len(session_ids)}",
        "",
        f"## VERDICT: {verdict}",
        "",
        "## Promoted",
        "",
    ]
    if promoted:
        lines.append("| Session | Topic | Destination |")
        lines.append("|---------|-------|-------------|")
        for sid, topic, dest in promoted:
            lines.append(f"| `{sid}` | {topic} | {dest} |")
    else:
        lines.append("(none)")

    lines.extend(["", "## Not promoted (with reason)", ""])
    if not_promoted:
        lines.append("| Session | Reason |")
        lines.append("|---------|--------|")
        for sid, reason in not_promoted:
            lines.append(f"| `{sid}` | {reason} |")
    else:
        lines.append("(none)")
    lines.append("")
    return "\n".join(lines)
