"""Ingest lossless revisions: raw transcript + chunks + packet index."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .checkpoint import init_checkpoints, save_checkpoints
from .chunks import rebuild_transcript, split_turns_into_chunks, write_chunk_files
from .revision import PIPELINE_VERSION, canonical_turns_json, compute_revision_id, sha256_hex

PREVIEW_CHARS = 240


def revisions_root(distill_dir: Path) -> Path:
    return distill_dir / "revisions"


def revision_dir_for(distill_dir: Path, session_id: str, revision_id: str) -> Path:
    return revisions_root(distill_dir) / session_id / revision_id


def ingest_revision(
    distill_dir: Path,
    *,
    session_id: str,
    platform: str,
    turns: list[dict[str, Any]],
    source_fingerprint: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    chunk_max_chars: int = 32_000,
) -> tuple[str, Path, dict[str, Any]]:
    metadata = metadata or {}
    revision_id = compute_revision_id(session_id, platform, turns, source_fingerprint)
    revision_dir = revision_dir_for(distill_dir, session_id, revision_id)
    raw_dir = revision_dir / "raw"
    chunks_dir = revision_dir / "chunks"
    raw_dir.mkdir(parents=True, exist_ok=True)

    raw_path = raw_dir / "transcript.json"
    raw_text = json.dumps(turns, ensure_ascii=False, indent=2) + "\n"
    raw_path.write_text(raw_text, encoding="utf-8")

    chunks = split_turns_into_chunks(turns, max_chars=chunk_max_chars)
    chunk_manifest = write_chunk_files(chunks_dir, chunks)

    checkpoints_path = revision_dir / "checkpoints.json"
    save_checkpoints(checkpoints_path, init_checkpoints([entry["chunk_id"] for entry in chunk_manifest]))

    manifest = {
        "version": 2,
        "pipeline_version": PIPELINE_VERSION,
        "session_id": session_id,
        "platform": platform,
        "revision_id": revision_id,
        "created_at": _now_iso(),
        "source_fingerprint": source_fingerprint,
        "normalized_transcript_sha256": sha256_hex(canonical_turns_json(turns)),
        "turn_count": len(turns),
        "chunk_count": len(chunk_manifest),
        "chunks": chunk_manifest,
        "metadata": metadata,
        "raw_path": "raw/transcript.json",
        "packet_path": "packet.md",
    }
    (revision_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    packet_text = render_packet_index(
        session_id=session_id,
        platform=platform,
        revision_id=revision_id,
        revision_dir=revision_dir,
        turns=turns,
        chunk_manifest=chunk_manifest,
        metadata=metadata,
        parse_counters=metadata.get("parse_counters") or {},
    )
    (revision_dir / "packet.md").write_text(packet_text, encoding="utf-8")

    audit = {
        "coverage": "lossless",
        "revision_id": revision_id,
        "turns": len(turns),
        "chunks": len(chunk_manifest),
        "warnings": [],
    }
    return revision_id, revision_dir, audit


def render_packet_index(
    *,
    session_id: str,
    platform: str,
    revision_id: str,
    revision_dir: Path,
    turns: list[dict[str, Any]],
    chunk_manifest: list[dict[str, Any]],
    metadata: dict[str, Any],
    parse_counters: dict[str, Any],
) -> str:
    lines = [
        f"# Session Packet Index: {session_id}",
        "",
        "## Metadata",
        "",
        f"- Platform: `{platform}`",
        f"- Revision: `{revision_id}`",
        f"- Pipeline: `{PIPELINE_VERSION}`",
        f"- Lossless raw: `{revision_dir / 'raw' / 'transcript.json'}`",
        f"- Turn count: {len(turns)}",
        f"- Chunk count: {len(chunk_manifest)}",
        f"- Queue status: `{metadata.get('status', 'new')}`",
    ]
    title = metadata.get("thread_name") or metadata.get("name") or ""
    if title:
        lines.append(f"- Title: {title}")
    workspace = metadata.get("workspace") or metadata.get("cwd") or metadata.get("project_path") or ""
    if workspace:
        lines.append(f"- Workspace: `{workspace}`")

    lines.extend(
        [
            "",
            "## Packet Audit",
            "",
            "- Coverage: `lossless`",
            f"- Turns rendered: {len(turns)}",
            f"- Chunks stored: {len(chunk_manifest)}",
            "- Summary view below is **non-authoritative**; use chunk JSON or raw transcript for promotion evidence.",
        ]
    )
    for key, value in parse_counters.items():
        if value:
            lines.append(f"- {str(key).replace('_', ' ').title()}: {value}")

    lines.extend(["", "## Chunk Index", "", "| Chunk | Turns | SHA256 (prefix) | Path |", "| --- | --- | --- | --- |"])
    for entry in chunk_manifest:
        lines.append(
            f"| `{entry['chunk_id']}` | {entry['turn_count']} | `{entry['sha256'][:12]}` | `{entry['path']}` |"
        )

    lines.extend(["", "## Turn Preview (non-authoritative)", ""])
    for index, turn in enumerate(turns, start=1):
        preview = _turn_preview(turn)
        lines.extend([f"### Turn {index}", "", f"- Turn id: `{turn.get('turn_id', '')}`", "", "```text", preview, "```", ""])

    lines.extend(
        [
            "",
            "## Distillation Reminder",
            "",
            "- Read `references/distillation-rules.md` before promotion.",
            "- Use raw transcript or chunk files for evidence; do not promote from preview alone.",
            "- Session note must include `## Final Session Review` before `mark distilled`.",
            "",
            "## Rebuild",
            "",
            f"```python",
            f"# chunks → full transcript",
            f"from distill_core.chunks import rebuild_transcript",
            f"rebuild_transcript(Path('{revision_dir / 'chunks'}'), chunk_manifest)",
            f"```",
            "",
        ]
    )
    return "\n".join(lines)


def verify_revision_rebuild(revision_dir: Path) -> tuple[bool, str]:
    manifest = json.loads((revision_dir / "manifest.json").read_text(encoding="utf-8"))
    raw_turns = json.loads((revision_dir / "raw" / "transcript.json").read_text(encoding="utf-8"))
    rebuilt = rebuild_transcript(revision_dir / "chunks", manifest.get("chunks") or [])
    if canonical_turns_json(raw_turns) != canonical_turns_json(rebuilt):
        return False, "rebuilt transcript does not match raw"
    return True, "ok"


def _turn_preview(turn: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("user_messages", "assistant_updates", "final_answers", "plans"):
        for value in turn.get(key) or []:
            text = str(value).strip()
            if text:
                parts.append(text)
    joined = "\n---\n".join(parts) if parts else "(empty turn)"
    if len(joined) <= PREVIEW_CHARS:
        return joined
    return joined[: PREVIEW_CHARS - 20].rstrip() + "\n\n[preview truncated]"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
