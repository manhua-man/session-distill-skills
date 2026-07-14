"""Manifest queue transitions (growth → redistill)."""

from __future__ import annotations

from typing import Any

BUNDLEABLE_STATUSES = frozenset({"new", "bundled", "pending_redistill"})
ALLOWED_STATUSES = frozenset({"new", "bundled", "distilled", "skipped", "pending_redistill"})


def needs_redistill(session: dict[str, Any], current_revision_id: str | None = None) -> bool:
    last = session.get("last_distilled_revision_id") or ""
    current = current_revision_id or session.get("current_revision_id") or ""
    if not last:
        return False
    if not current:
        return session.get("source_fingerprint") != session.get("last_indexed_fingerprint")
    return current != last


def compute_queue_status_on_index(
    old: dict[str, Any],
    *,
    source_fingerprint: str,
    current_revision_id: str | None = None,
) -> str:
    status = old.get("status", "new")
    if status not in ALLOWED_STATUSES:
        status = "new"

    if status == "distilled":
        if needs_redistill(
            {**old, "source_fingerprint": source_fingerprint, "current_revision_id": current_revision_id},
            current_revision_id=current_revision_id,
        ):
            return "pending_redistill"
        if source_fingerprint != old.get("last_indexed_fingerprint"):
            return "pending_redistill"
    elif status == "pending_redistill":
        return "pending_redistill"

    return status


def is_bundleable(session: dict[str, Any], *, force: bool = False) -> bool:
    status = session.get("status", "new")
    if force:
        return status in ALLOWED_STATUSES - {"skipped"}
    return status in BUNDLEABLE_STATUSES
