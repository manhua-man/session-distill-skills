#!/usr/bin/env python3
"""Shared Deep Distill helpers (Grok paradigm) for all session-distill runners."""

from __future__ import annotations

import re
from typing import Any

FINAL_SECTION = re.compile(r"### Final Answers\s+```text\s+(.*?)\s+```", re.DOTALL)
USER_QUERY = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL | re.IGNORECASE)

ANSWER_STATUSES = frozenset({"ANSWERED", "PARTIAL", "UNANSWERED", "CONTRADICTED", "NOT_APPLICABLE", "PENDING"})


def extract_claims(packet_text: str, meta: dict[str, Any]) -> list[str]:
    """Extract hypothesis claims from a packet (Final Answers first, then title)."""
    claims: list[str] = []
    title = (meta.get("thread_name") or meta.get("name") or "").strip()
    if title and title.lower() != "untitled":
        claims.append(f"Session topic: {title}")

    for match in FINAL_SECTION.finditer(packet_text):
        body = match.group(1).strip()
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("[MODE:"):
                continue
            if line.startswith("#"):
                continue
            if line.startswith("|"):
                continue
            if len(line) > 20:
                claims.append(line[:500])
        if len(claims) <= 1 and body:
            claims.append(body[:800])

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


def infer_lens(claim: str) -> str:
    lower = claim.lower()
    if any(k in lower for k in ("mcp", "postgres", "docker", "pwsh", "github", "shell")):
        return "runtime"
    if any(k in lower for k in ("deploy", "smoke", "nginx", "发版", "production")):
        return "deploy"
    if any(k in lower for k in ("agents", "claude", "docs/", "skill", "steering")):
        return "ai-entry"
    if any(k in lower for k in ("payment", "refund", "order", "alipay", "wechat")):
        return "payment"
    if any(k in lower for k in ("auth", "uos", "login", "persona")):
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
) -> str:
    title = meta.get("thread_name") or meta.get("name") or session_id
    project = project_path or meta.get("project_path") or meta.get("workspace") or ""
    lines = [
        f"# Answer Packet: {session_id}",
        "",
        "## Scope",
        f"- Platform: {platform}",
        f"- Title: {title}",
        f"- Project: {project}",
        "- Phase: extract complete; **verify each Q with toolchain before promotion**",
        "",
        "## Claims extracted (hypotheses)",
        "",
    ]
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
