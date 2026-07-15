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


def _normalize_review_text(text: str) -> str:
    return re.sub(r"\*+", "", text.lower())


def validate_final_review(note_text: str) -> list[str]:
    errors: list[str] = []
    lower = note_text.lower()
    if FINAL_REVIEW_HEADING.lower() not in lower:
        errors.append("session note missing ## Final Session Review section")
        return errors

    section = _extract_section(note_text)
    section_lower = _normalize_review_text(section)

    for label, pattern in _REQUIRED_FIELDS:
        if not re.search(pattern, section_lower):
            errors.append(f"Final Session Review missing field: {label}")

    if "promotion allowed: yes" in section_lower and "evidence status: all answered" not in section_lower:
        errors.append("Promotion allowed: yes requires Evidence status: all ANSWERED")

    return errors


def promotion_allowed(note_text: str) -> bool:
    section = _normalize_review_text(_extract_section(note_text))
    return "promotion allowed: yes" in section and not promotion_blocked_reasons(note_text)


def promotion_blocked_reasons(note_text: str) -> list[str]:
    errors = validate_final_review(note_text)
    section = _normalize_review_text(_extract_section(note_text))
    if "promotion allowed: no" in section:
        errors.append("Final Session Review blocks promotion (Promotion allowed: no)")
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
