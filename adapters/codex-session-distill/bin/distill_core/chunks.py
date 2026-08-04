"""Lossless turn chunking and transcript rebuild."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .revision import sha256_hex

DEFAULT_CHUNK_MAX_CHARS = 32_000


def _turn_size(turn: dict[str, Any]) -> int:
    return len(json.dumps(turn, ensure_ascii=False))


def split_turns_into_chunks(
    turns: list[dict[str, Any]],
    *,
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current_turns: list[dict[str, Any]] = []
    current_size = 0
    ordinal = 0

    for turn in turns:
        turn_size = _turn_size(turn)
        if current_turns and current_size + turn_size > max_chars:
            ordinal += 1
            chunks.append(_make_chunk(ordinal, current_turns))
            current_turns = []
            current_size = 0
        current_turns.append(turn)
        current_size += turn_size

    if current_turns:
        ordinal += 1
        chunks.append(_make_chunk(ordinal, current_turns))

    return chunks


def _make_chunk(ordinal: int, turns: list[dict[str, Any]]) -> dict[str, Any]:
    body = json.dumps(turns, ensure_ascii=False, sort_keys=True)
    return {
        "chunk_id": f"{ordinal:04d}",
        "ordinal": ordinal,
        "turn_count": len(turns),
        "turn_ids": [turn.get("turn_id", "") for turn in turns],
        "byte_size": len(body.encode("utf-8")),
        "sha256": sha256_hex(body),
        "turns": turns,
    }


def write_chunk_files(chunks_dir: Path, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    manifest_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        path = chunks_dir / f"{chunk_id}.json"
        payload = {
            "chunk_id": chunk_id,
            "ordinal": chunk["ordinal"],
            "turn_count": chunk["turn_count"],
            "turn_ids": chunk["turn_ids"],
            "byte_size": chunk["byte_size"],
            "sha256": chunk["sha256"],
            "turns": chunk["turns"],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        path.write_text(text, encoding="utf-8")
        manifest_chunks.append(
            {
                "chunk_id": chunk_id,
                "ordinal": chunk["ordinal"],
                "path": f"chunks/{chunk_id}.json",
                "turn_count": chunk["turn_count"],
                "sha256": chunk["sha256"],
            }
        )
    return manifest_chunks


def load_chunk(chunk_path: Path) -> dict[str, Any]:
    return json.loads(chunk_path.read_text(encoding="utf-8"))


def rebuild_transcript(chunks_dir: Path, chunk_manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for entry in sorted(chunk_manifest, key=lambda item: item["ordinal"]):
        chunk = load_chunk(chunks_dir / f"{entry['chunk_id']}.json")
        turns.extend(chunk.get("turns") or [])
    return turns
