"""Durable per-chunk checkpoint state."""

from __future__ import annotations

import json
import os
import socket
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_LEASE_SECONDS = 600
DEFAULT_LOCK_WAIT_SECONDS = 5.0
STALE_LOCK_SECONDS = 60.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _lease_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _new_checkpoint_entry(chunk_id: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "state": "pending",
        "attempt": 0,
        "lease_owner": "",
        "lease_expires_at": "",
        "result_path": "",
        "error": None,
    }


def init_checkpoints(chunk_ids: list[str]) -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": _now_iso(),
        "chunks": {chunk_id: _new_checkpoint_entry(chunk_id) for chunk_id in chunk_ids},
    }


def load_checkpoints(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updated_at": "", "chunks": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_checkpoints(path: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = _now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp_name).replace(path)
    finally:
        tmp_path = Path(tmp_name)
        if tmp_path.exists():
            tmp_path.unlink()


@contextmanager
def checkpoint_lock(
    path: Path,
    *,
    wait_seconds: float = DEFAULT_LOCK_WAIT_SECONDS,
) -> Iterator[None]:
    """Serialize checkpoint read-modify-write operations across processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + wait_seconds
    acquired = False
    while not acquired:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(_lease_owner())
            acquired = True
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > STALE_LOCK_SECONDS:
                    lock_path.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"checkpoint lock timed out: {lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def ensure_checkpoints(path: Path, chunk_ids: list[str]) -> dict[str, Any]:
    """Create missing chunk entries while holding the checkpoint lock."""
    with checkpoint_lock(path):
        checkpoints = load_checkpoints(path)
        chunks = checkpoints.setdefault("chunks", {})
        changed = not path.exists()
        for chunk_id in chunk_ids:
            if chunk_id not in chunks:
                chunks[chunk_id] = _new_checkpoint_entry(chunk_id)
                changed = True
        if changed:
            save_checkpoints(path, checkpoints)
        return checkpoints


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
        _new_checkpoint_entry(chunk_id),
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


def claim_chunk_file(
    path: Path,
    chunk_id: str,
    *,
    force: bool = False,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> tuple[bool, str, dict[str, Any]]:
    """Atomically load, claim, and persist one chunk lease."""
    with checkpoint_lock(path):
        checkpoints = load_checkpoints(path)
        ok, message = claim_chunk(
            checkpoints,
            chunk_id,
            force=force,
            lease_seconds=lease_seconds,
        )
        if ok:
            save_checkpoints(path, checkpoints)
        return ok, message, checkpoints


def finish_chunk_file(
    path: Path,
    chunk_id: str,
    *,
    lease_owner: str,
    result_path: str = "",
    error: str | None = None,
) -> tuple[bool, str]:
    """Persist a terminal result only while the caller still owns the lease."""
    with checkpoint_lock(path):
        checkpoints = load_checkpoints(path)
        entry = (checkpoints.get("chunks") or {}).get(chunk_id)
        if not entry:
            return False, "chunk checkpoint missing"
        if entry.get("state") != "running" or entry.get("lease_owner") != lease_owner:
            return False, "chunk lease lost"
        if error is None:
            entry["state"] = "done"
            entry["result_path"] = result_path
            entry["error"] = None
        else:
            entry["state"] = "failed"
            entry["error"] = error
        save_checkpoints(path, checkpoints)
        return True, "finished"
