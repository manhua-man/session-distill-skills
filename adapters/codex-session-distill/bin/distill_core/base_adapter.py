"""Base platform adapter class for session distillation."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .adapter_common import (
    ReadText,
    bundle_lossless_session,
    index_session_entry,
    validate_distilled_note,
    write_json,
)
from .final_review import validate_final_review
from .ingest import ingest_revision
from .queue import BUNDLEABLE_STATUSES, compute_queue_status_on_index


def now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class BasePlatformAdapter(ABC):
    """Abstract base class defining the standard interface and shared behaviors for all platform adapters."""

    def __init__(
        self,
        platform_id: str,
        distill_dir: Path,
        *,
        manifest_filename: str = "manifest.json",
        knowledge_filename: str = "knowledge-base.md",
    ):
        self.platform_id = platform_id
        self.distill_dir = distill_dir.resolve()
        self.manifest_file = self.distill_dir / manifest_filename
        self.knowledge_file = self.distill_dir / knowledge_filename
        self.packets_dir = self.distill_dir / "packets"
        self.distilled_dir = self.distill_dir / "distilled" / "sessions"
        self.answer_packets_dir = self.distill_dir / "distilled" / "answer-packets"

    def ensure_dirs(self) -> None:
        """Create standard directories and baseline files if missing."""
        self.distill_dir.mkdir(parents=True, exist_ok=True)
        self.packets_dir.mkdir(parents=True, exist_ok=True)
        self.distilled_dir.mkdir(parents=True, exist_ok=True)
        self.answer_packets_dir.mkdir(parents=True, exist_ok=True)

        if not self.knowledge_file.exists():
            self.knowledge_file.write_text(
                f"# Session Distill Knowledge Base ({self.platform_id})\n",
                encoding="utf-8",
            )

        if not self.manifest_file.exists():
            base_manifest = {"version": 1, "updated_at": now_iso(), "sessions": []}
            self.save_manifest(base_manifest)

    def load_manifest(self) -> dict[str, Any]:
        """Load manifest JSON file or return default empty manifest."""
        if self.manifest_file.exists():
            try:
                return json.loads(self.manifest_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"version": 1, "updated_at": "", "sessions": []}

    def save_manifest(self, manifest: dict[str, Any]) -> None:
        """Save manifest safely with UTF-8 encoding and indentation."""
        manifest["updated_at"] = now_iso()
        write_json(self.manifest_file, manifest)

    def find_session_in_manifest(self, manifest: dict[str, Any], session_id: str) -> dict[str, Any] | None:
        """Find a session dict in manifest by session_id."""
        for s in manifest.get("sessions", []):
            if s.get("session_id") == session_id:
                return s
        return None

    def upsert_session_in_manifest(self, manifest: dict[str, Any], session_entry: dict[str, Any]) -> None:
        """Insert or update a session entry in manifest."""
        session_id = session_entry.get("session_id")
        sessions = manifest.setdefault("sessions", [])
        for i, s in enumerate(sessions):
            if s.get("session_id") == session_id:
                sessions[i] = session_entry
                return
        sessions.append(session_entry)

    def create_index_entry(
        self,
        old_entry: dict[str, Any] | None,
        *,
        session_id: str,
        source_fields: dict[str, Any],
        base_meta: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute status and index metadata for a session."""
        return index_session_entry(
            old_entry or {},
            session_id=session_id,
            source_fields=source_fields,
            base_meta=base_meta,
        )

    def bundle_session(
        self,
        session_entry: dict[str, Any],
        turns: list[dict[str, Any]],
        source_fingerprint: dict[str, Any],
        *,
        packet_path: Path | None = None,
        read_text: ReadText | None = None,
        parse_counters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ingest revision, construct lossless packet.md and return audit metadata."""
        if packet_path is None:
            packet_path = self.packets_dir / f"{session_entry['session_id']}.md"
        reader = read_text or (lambda p: p.read_text(encoding="utf-8", errors="replace"))

        return bundle_lossless_session(
            distill_dir=self.distill_dir,
            session=session_entry,
            platform=self.platform_id,
            turns=turns,
            source_fingerprint=source_fingerprint,
            packet_path=packet_path,
            read_text=reader,
            parse_counters=parse_counters,
        )

    def validate_distilled_note(
        self,
        session_id: str,
        *,
        packet_name: str | None = None,
        read_text: ReadText | None = None,
        extra_errors: Callable[[str, str], list[str]] | None = None,
    ) -> list[str]:
        """Validate a distilled review note against lossless packet and quality gates."""
        reader = read_text or (lambda p: p.read_text(encoding="utf-8", errors="replace"))
        return validate_distilled_note(
            session_id=session_id,
            packets_dir=self.packets_dir,
            distilled_dir=self.distilled_dir,
            read_text=reader,
            packet_name=packet_name,
            extra_errors=extra_errors,
        )

    def filter_sessions_by_project(
        self,
        sessions: list[dict[str, Any]],
        project_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Filter sessions matching a given project query."""
        if not project_filter:
            return sessions

        query = project_filter.lower().replace("\\", "/").strip()
        matched = []
        for s in sessions:
            project_val = str(s.get("project") or "").lower().replace("\\", "/")
            workspace_val = str(s.get("workspace") or "").lower().replace("\\", "/")
            session_path = str(s.get("session_path") or s.get("path") or "").lower().replace("\\", "/")

            if query in project_val or query in workspace_val or query in session_path:
                matched.append(s)
        return matched

    def get_summary_stats(self, manifest: dict[str, Any] | None = None) -> dict[str, int]:
        """Compute status counts for the adapter's sessions."""
        m = manifest or self.load_manifest()
        counts: dict[str, int] = {
            "total": 0,
            "new": 0,
            "bundled": 0,
            "distilled": 0,
            "skipped": 0,
            "pending_redistill": 0,
        }
        for s in m.get("sessions", []):
            counts["total"] += 1
            st = s.get("status", "new")
            counts[st] = counts.get(st, 0) + 1
        return counts

    @abstractmethod
    def index(self, project_filter: str | None = None) -> int:
        """Scan platform session store and update manifest."""
        pass

    @abstractmethod
    def parse_session_turns(self, session_entry: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract canonical turns from platform raw session representation."""
        pass
