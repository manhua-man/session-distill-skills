"""Deep distill extract phase with per-chunk checkpoint resume."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .checkpoint import claim_chunk_file, ensure_checkpoints, finish_chunk_file, load_checkpoints

EXTRACT_CHECKPOINT_FILE = "extract-checkpoints.json"
ClaimExtractor = Callable[[list[dict[str, Any]], dict[str, Any]], list[str]]


def _dedupe_claims(claims: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for claim in claims:
        key = claim.lower()
        if not claim.strip() or key in seen:
            continue
        seen.add(key)
        out.append(claim)
    return out


def _init_extract_checkpoints(chunk_ids: list[str]) -> dict[str, Any]:
    return {
        "version": 1,
        "phase": "extract",
        "chunks": {
            chunk_id: {
                "chunk_id": chunk_id,
                "state": "pending",
                "attempt": 0,
                "lease_owner": "",
                "lease_expires_at": "",
                "result_path": "",
                "error": None,
            }
            for chunk_id in chunk_ids
        },
    }


def _merge_extract_checkpoints(existing: dict[str, Any], chunk_ids: list[str]) -> dict[str, Any]:
    merged = _init_extract_checkpoints(chunk_ids)
    old_chunks = (existing or {}).get("chunks") or {}
    for chunk_id in chunk_ids:
        if chunk_id in old_chunks:
            merged["chunks"][chunk_id] = old_chunks[chunk_id]
    return merged


def extract_claims_chunked(
    revision_dir: Path,
    meta: dict[str, Any],
    claim_extractor: ClaimExtractor,
    *,
    force: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    manifest_path = revision_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"revision manifest missing: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk_manifest = manifest.get("chunks") or []
    chunk_ids = [entry["chunk_id"] for entry in sorted(chunk_manifest, key=lambda item: item["ordinal"])]

    cp_path = revision_dir / EXTRACT_CHECKPOINT_FILE
    ensure_checkpoints(cp_path, chunk_ids)

    all_claims: list[str] = []
    resumed = 0
    processed = 0
    leased_elsewhere = 0

    for entry in sorted(chunk_manifest, key=lambda item: item["ordinal"]):
        chunk_id = entry["chunk_id"]
        checkpoints = _merge_extract_checkpoints(load_checkpoints(cp_path), chunk_ids)
        cp_entry = checkpoints["chunks"][chunk_id]
        if cp_entry.get("state") == "done" and not force:
            result_path = cp_entry.get("result_path")
            if result_path:
                claims_path = revision_dir / result_path
                if claims_path.exists():
                    payload = json.loads(claims_path.read_text(encoding="utf-8"))
                    all_claims.extend(payload.get("claims") or [])
                    resumed += 1
                    continue

        ok, message, checkpoints = claim_chunk_file(cp_path, chunk_id, force=force)
        if not ok:
            cp_entry = (checkpoints.get("chunks") or {}).get(chunk_id, {})
            if cp_entry.get("state") == "done":
                result_path = cp_entry.get("result_path")
                if result_path and (revision_dir / result_path).exists():
                    payload = json.loads((revision_dir / result_path).read_text(encoding="utf-8"))
                    all_claims.extend(payload.get("claims") or [])
                    resumed += 1
                    continue
            if cp_entry.get("state") == "running":
                leased_elsewhere += 1
                continue
            raise RuntimeError(f"cannot claim chunk {chunk_id}: {message}")

        cp_entry = checkpoints["chunks"][chunk_id]
        lease_owner = cp_entry["lease_owner"]
        attempt = cp_entry["attempt"]

        try:
            chunk_path = revision_dir / "chunks" / f"{chunk_id}.json"
            chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
            turns = chunk.get("turns") or []
            chunk_claims = claim_extractor(turns, meta)
            owner_hash = hashlib.sha256(lease_owner.encode("utf-8")).hexdigest()[:12]
            result_rel = f"chunks/{chunk_id}.attempt-{attempt}-{owner_hash}.claims.json"
            result_path = revision_dir / result_rel
            result_path.write_text(
                json.dumps({"chunk_id": chunk_id, "claims": chunk_claims}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            finished, message = finish_chunk_file(
                cp_path,
                chunk_id,
                lease_owner=lease_owner,
                result_path=result_rel,
            )
            if not finished:
                raise RuntimeError(f"cannot finish chunk {chunk_id}: {message}")
            all_claims.extend(chunk_claims)
            processed += 1
        except Exception as exc:
            finish_chunk_file(cp_path, chunk_id, lease_owner=lease_owner, error=str(exc))
            raise

    stats = {
        "mode": "chunked",
        "revision_id": manifest.get("revision_id"),
        "chunks_total": len(chunk_ids),
        "chunks_resumed": resumed,
        "chunks_processed": processed,
        "chunks_leased_elsewhere": leased_elsewhere,
    }
    return _dedupe_claims(all_claims)[:24], stats


def extract_session_claims(
    *,
    session_meta: dict[str, Any],
    packet_text: str,
    claim_extractor: ClaimExtractor,
    packet_claim_extractor: Callable[[str, dict[str, Any]], list[str]],
    force: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    revision_path = session_meta.get("revision_path")
    if revision_path:
        revision_dir = Path(revision_path)
        if revision_dir.exists() and (revision_dir / "manifest.json").exists():
            return extract_claims_chunked(revision_dir, session_meta, claim_extractor, force=force)

    claims = packet_claim_extractor(packet_text, session_meta)
    return claims, {"mode": "packet_fallback"}
