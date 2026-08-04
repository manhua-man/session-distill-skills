"""Stable idempotent candidate identifiers."""

from __future__ import annotations

import re
import unicodedata

from .revision import PIPELINE_VERSION, sha256_hex

_WS_RE = re.compile(r"\s+")


def normalize_claim(claim: str) -> str:
    text = unicodedata.normalize("NFKC", claim or "").strip().lower()
    return _WS_RE.sub(" ", text)


def make_candidate_id(
    *,
    source_revision_id: str,
    candidate_kind: str,
    normalized_claim: str,
    pipeline_version: str = PIPELINE_VERSION,
) -> str:
    payload = "|".join([source_revision_id, pipeline_version, candidate_kind, normalized_claim])
    return sha256_hex(payload)[:20]
