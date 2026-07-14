"""Durable per-chunk checkpoint state."""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_LEASE_SECONDS = 600


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _lease_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def init_checkpoints(chunk_ids: list[str]) -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": _now_iso(),
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


def load_checkpoints(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updated_at": "", "chunks": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_checkpoints(path: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = _now_iso()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _lease_expired(entry: dict[str, Any], now: datetime) -> bool:
    expires = entry.get("lease_expires_at") or ""
    if not expires:
        return True
    try:
        expiry = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return True
    return expiry <= now


def claim_chunk(
    checkpoints: dict[str, Any],
    chunk_id: str,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    force: bool = False,
) -> tuple[bool, str]:
    chunks = checkpoints.setdefault("chunks", {})
    entry = chunks.setdefault(
        chunk_id,
        {
            "chunk_id": chunk_id,
            "state": "pending",
            "attempt": 0,
            "lease_owner": "",
            "lease_expires_at": "",
            "result_path": "",
            "error": None,
        },
    )
    now = datetime.now(timezone.utc)
    state = entry.get("state", "pending")

    if state == "done" and not force:
        return False, "chunk already done"

    if state == "running" and not _lease_expired(entry, now) and not force:
        return False, f"chunk leased by {entry.get('lease_owner')}"

    expires = now + timedelta(seconds=lease_seconds)
    entry["state"] = "running"
    entry["attempt"] = int(entry.get("attempt", 0)) + 1
    entry["lease_owner"] = _lease_owner()
    entry["lease_expires_at"] = expires.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    entry["error"] = None
    return True, "claimed"
