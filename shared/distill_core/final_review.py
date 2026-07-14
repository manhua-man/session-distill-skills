"""Mandatory final-session review block."""

from __future__ import annotations

import re

FINAL_REVIEW_HEADING = "## Final Session Review"

_REQUIRED_FIELDS = (
    ("final user request", r"final user request\s*:"),
    ("final outcome", r"final outcome\s*:"),
    ("last turn state", r"last turn state\s*:"),
    ("contradictions", r"contradictions\s*:"),
    ("open items", r"open items\s*:"),
    ("evidence status", r"evidence status\s*:"),
    ("promotion allowed", r"promotion allowed\s*:"),
)


def validate_final_review(note_text: str) -> list[str]:
    errors: list[str] = []
    lower = note_text.lower()
    if FINAL_REVIEW_HEADING.lower() not in lower:
        errors.append("session note missing ## Final Session Review section")
        return errors

    section = _extract_section(note_text)
    section_lower = section.lower()

    for label, pattern in _REQUIRED_FIELDS:
        if not re.search(pattern, section_lower):
            errors.append(f"Final Session Review missing field: {label}")

    if "promotion allowed: yes" in section_lower and "evidence status: all answered" not in section_lower:
        if "evidence status:" in section_lower and "partial" in section_lower.split("evidence status:", 1)[1][:80]:
            errors.append("Promotion allowed: yes conflicts with partial evidence status")

    return errors


def _extract_section(note_text: str) -> str:
    lines = note_text.splitlines()
    capture = False
    collected: list[str] = []
    for line in lines:
        if line.strip().lower() == FINAL_REVIEW_HEADING.lower():
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture:
            collected.append(line)
    return "\n".join(collected)
