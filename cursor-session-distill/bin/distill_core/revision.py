"""Content-hash revision identifiers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

PIPELINE_VERSION = "deep-distill-v2"


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_turns_json(turns: list[dict[str, Any]]) -> str:
    return json.dumps(turns, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_revision_id(
    session_id: str,
    platform: str,
    turns: list[dict[str, Any]],
    source_fingerprint: dict[str, Any] | None = None,
) -> str:
    """Identity from canonical transcript content only (not mtime/size)."""
    _ = source_fingerprint  # provenance only; stored on revision manifest, not in ID
    payload = {
        "session_id": session_id,
        "platform": platform,
        "pipeline_version": PIPELINE_VERSION,
        "normalized_transcript_sha256": sha256_hex(canonical_turns_json(turns)),
    }
    return sha256_hex(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]


def compute_source_fingerprint(fields: dict[str, Any]) -> str:
    """Lightweight fingerprint for index-time growth detection (no full parse)."""
    normalized = {key: fields[key] for key in sorted(fields) if fields.get(key) is not None}
    return sha256_hex(json.dumps(normalized, ensure_ascii=False, sort_keys=True))[:16]
