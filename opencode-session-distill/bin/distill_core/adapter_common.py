"""Shared adapter helpers for platform session-distill CLIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .final_review import validate_final_review
from .ingest import ingest_revision
from .queue import BUNDLEABLE_STATUSES, compute_queue_status_on_index
from .revision import compute_source_fingerprint

ReadText = Callable[[Path], str]


def messages_to_turns(messages: list[dict[str, Any]], *, turn_id_prefix: str = "turn") -> list[dict[str, Any]]:
    """Convert flat role/content rows into canonical turn objects."""
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def _new_turn(user_text: str) -> dict[str, Any]:
        return {
            "turn_id": f"{turn_id_prefix}-{len(turns) + 1}",
            "user_messages": [user_text] if user_text else [],
            "assistant_updates": [],
            "final_answers": [],
            "plans": [],
            "patches": [],
            "commands": [],
            "command_outputs": [],
            "system_events": [],
        }

    for message in messages:
        role = (message.get("role") or "").strip().lower()
        content = str(message.get("content") or "").strip()
        if role == "user":
            if current and (current["user_messages"] or current["assistant_updates"] or current["command_outputs"]):
                turns.append(current)
            current = _new_turn(content)
            continue
        if current is None:
            current = _new_turn("")
        if role == "assistant":
            if content:
                current["assistant_updates"].append(content)
                current["final_answers"].append(content)
        elif role == "tool":
            if content:
                current["command_outputs"].append({"call_id": message.get("tool_name") or "", "output": content})
        elif content:
            current["system_events"].append(f"{role}: {content[:300]}")

    if current and (
        current["user_messages"]
        or current["assistant_updates"]
        or current["command_outputs"]
        or current["system_events"]
    ):
        turns.append(current)
    return turns


def lines_to_turns(lines: list[str], *, turn_id_prefix: str = "turn") -> list[dict[str, Any]]:
    if not lines:
        return []
    return [
        {
            "turn_id": f"{turn_id_prefix}-1",
            "user_messages": lines[: max(1, len(lines) // 2)],
            "assistant_updates": lines[max(1, len(lines) // 2) : -1],
            "final_answers": [lines[-1]] if lines else [],
            "plans": [],
            "patches": [],
            "commands": [],
            "command_outputs": [],
            "system_events": [],
        }
    ]


def index_session_entry(
    old: dict[str, Any],
    *,
    session_id: str,
    source_fields: dict[str, Any],
    base_meta: dict[str, Any],
) -> dict[str, Any]:
    source_fp_hash = compute_source_fingerprint(source_fields)
    status = compute_queue_status_on_index(
        old,
        source_fingerprint=source_fp_hash,
        current_revision_id=old.get("current_revision_id"),
    )
    return {
        **base_meta,
        "session_id": session_id,
        "status": status,
        "source_fingerprint": source_fp_hash,
        "last_indexed_fingerprint": source_fp_hash,
        "current_revision_id": old.get("current_revision_id"),
        "last_distilled_revision_id": old.get("last_distilled_revision_id"),
        "revision_path": old.get("revision_path"),
        "bundle_path": old.get("bundle_path"),
        "bundle_source_last_write_time": old.get("bundle_source_last_write_time"),
        "bundle_source_size_bytes": old.get("bundle_source_size_bytes"),
        "distilled_path": old.get("distilled_path"),
        "notes": old.get("notes", ""),
    }


def bundle_lossless_session(
    *,
    distill_dir: Path,
    session: dict[str, Any],
    platform: str,
    turns: list[dict[str, Any]],
    source_fingerprint: dict[str, Any],
    packet_path: Path,
    read_text: ReadText,
    parse_counters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {**session, "parse_counters": parse_counters or {}}
    revision_id, revision_dir, audit = ingest_revision(
        distill_dir,
        session_id=session["session_id"],
        platform=platform,
        turns=turns,
        source_fingerprint=source_fingerprint,
        metadata=metadata,
    )
    packet_path.write_text(read_text(revision_dir / "packet.md"), encoding="utf-8")
    session["status"] = "bundled"
    session["bundle_path"] = str(packet_path)
    session["bundle_source_last_write_time"] = session.get("last_write_time")
    session["bundle_source_size_bytes"] = session.get("size_bytes")
    session["current_revision_id"] = revision_id
    session["revision_path"] = str(revision_dir)
    return audit


def validate_distilled_note(
    *,
    session_id: str,
    packets_dir: Path,
    distilled_dir: Path,
    read_text: ReadText,
    packet_name: str | None = None,
    extra_errors: Callable[[str, str], list[str]] | None = None,
) -> list[str]:
    errors: list[str] = []
    packet_path = packets_dir / (packet_name or f"{session_id}.md")
    note_path = distilled_dir / f"{session_id}.md"
    if not packet_path.exists():
        errors.append(f"packet missing: {packet_path}")
    if not note_path.exists():
        errors.append(f"session note missing: {note_path}")
        return errors
    note_text = read_text(note_path)
    note_lower = note_text.lower()
    packet_text = read_text(packet_path) if packet_path.exists() else ""
    if "Coverage: `partial`" in packet_text and not any(
        marker in note_lower for marker in ["raw transcript", "raw jsonl", "raw review", "chat_history", "原始", "补看"]
    ):
        errors.append("partial packet requires raw transcript review note")
    errors.extend(validate_final_review(note_text))
    if not any(
        marker in note_lower for marker in ["promotion decision", "memory decision", "no promotion", "不提升", "知识", "promote"]
    ):
        errors.append("session note must record promotion/no-promotion decision")
    if extra_errors:
        errors.extend(extra_errors(note_text, packet_text))
    return errors


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
