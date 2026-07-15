"""Shared session-distill core (lossless revisions, chunks, queue, checkpoints)."""

from .candidate_id import make_candidate_id, normalize_claim
from .checkpoint import (
    claim_chunk,
    claim_chunk_file,
    ensure_checkpoints,
    finish_chunk_file,
    init_checkpoints,
    load_checkpoints,
    save_checkpoints,
)
from .chunks import rebuild_transcript, split_turns_into_chunks
from .final_review import FINAL_REVIEW_HEADING, validate_final_review
from .deep_run import extract_claims_chunked, extract_session_claims
from .ingest import ingest_revision, revision_dir_for, revisions_root
from .queue import BUNDLEABLE_STATUSES, compute_queue_status_on_index, needs_redistill
from .revision import PIPELINE_VERSION, compute_revision_id, compute_source_fingerprint, sha256_hex

__all__ = [
    "PIPELINE_VERSION",
    "BUNDLEABLE_STATUSES",
    "FINAL_REVIEW_HEADING",
    "claim_chunk",
    "claim_chunk_file",
    "compute_queue_status_on_index",
    "compute_revision_id",
    "compute_source_fingerprint",
    "ensure_checkpoints",
    "finish_chunk_file",
    "init_checkpoints",
    "extract_claims_chunked",
    "extract_session_claims",
    "ingest_revision",
    "load_checkpoints",
    "make_candidate_id",
    "needs_redistill",
    "normalize_claim",
    "rebuild_transcript",
    "revision_dir_for",
    "revisions_root",
    "save_checkpoints",
    "sha256_hex",
    "split_turns_into_chunks",
    "validate_final_review",
]
