import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "packet-memory-export.py"


def load_module():
    spec = importlib.util.spec_from_file_location("packet_memory_export", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PacketMemoryExporterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.module = load_module()

        self.module.DISTILL_DIR = self.home / ".claude" / "session-distill"
        self.module.PACKETS_DIR = self.module.DISTILL_DIR / "packets"
        self.module.MEMORY_DRAFTS_DIR = self.module.DISTILL_DIR / "memory-drafts"
        self.module.SYNC_LISTS_DIR = self.module.DISTILL_DIR / "sync-lists"
        self.module.DISTILLED_DIR = self.module.DISTILL_DIR / "distilled" / "sessions"
        self.module.PACKETS_DIR.mkdir(parents=True, exist_ok=True)
        self.module.MEMORY_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        self.module.SYNC_LISTS_DIR.mkdir(parents=True, exist_ok=True)
        self.module.DISTILLED_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_distilled_note(self, session_id, promotion_allowed=True):
        promotion = "yes" if promotion_allowed else "no"
        note_path = self.module.DISTILLED_DIR / f"{session_id}.md"
        note_path.write_text(
            "\n".join(
                [
                    f"# Session Note: {session_id}",
                    "",
                    "## Final Session Review",
                    "- **Final user request:** test",
                    "- **Final outcome:** done",
                    "- **Last turn state:** completed",
                    "- **Contradictions:** none",
                    "- **Open items:** none",
                    "- **Evidence status:** all ANSWERED",
                    f"- **Promotion allowed:** {promotion}",
                ]
            ),
            encoding="utf-8",
        )
        return note_path

    def write_packet(self, session_id, coverage="high", warnings=None, turns=None, revision_id="rev-test-001"):
        warnings = warnings or []
        turns = turns or []
        packet_path = self.module.PACKETS_DIR / f"{session_id}.md"
        lines = [
            f"# Session Packet: {session_id}",
            "",
            "## Metadata",
            "",
            f"- Revision: `{revision_id}`",
            "",
            "## Packet Audit",
            "",
            f"- Coverage: `{coverage}`",
            f"- Turns rendered: {len(turns)}",
            "",
        ]
        if warnings:
            lines.extend(["### Audit Warnings", ""])
            for warning in warnings:
                lines.append(f"- {warning}")
            lines.append("")
        lines.extend(["### Lossy Transforms", "", "- Text blocks longer than 1200 chars are clipped.", ""])

        for number, turn in enumerate(turns, start=1):
            lines.extend(
                [
                    f"## Turn {number}",
                    "",
                    f"- Turn id: `turn-{number}`",
                    "",
                ]
            )
            if turn.get("final_answers"):
                lines.extend(["### Final Answers", ""])
                for text in turn["final_answers"]:
                    lines.extend(["```text", text, "```", ""])
            if turn.get("assistant_updates"):
                lines.extend(["### Assistant Updates", ""])
                for text in turn["assistant_updates"]:
                    lines.extend(["```text", text, "```", ""])
            if turn.get("commands"):
                lines.extend(["### Commands", ""])
                for command in turn["commands"]:
                    lines.append(f"- {command}")
                lines.append("")
            if turn.get("referenced_files"):
                lines.extend(["### Referenced Files", ""])
                for path in turn["referenced_files"]:
                    lines.append(f"- `{path}` (1)")
                lines.append("")

        packet_path.write_text("\n".join(lines), encoding="utf-8")
        return packet_path

    def test_export_creates_structured_memory_draft(self):
        packet_path = self.write_packet(
            "sample-session",
            turns=[
                {
                    "final_answers": [
                        "Default workflow should check auth.service.ts before changing login behavior.",
                        "Use rg auth.service when tracing authentication issues.",
                    ],
                    "commands": ["`Bash` rg auth.service"],
                    "referenced_files": ["packages/nestjs-server/src/modules/auth/auth.service.ts"],
                }
            ],
        )

        output_path = self.module.MEMORY_DRAFTS_DIR / "sample-session.json"
        self.module.cmd_export(packet_path=str(packet_path), force=True)
        draft = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertGreaterEqual(len(draft["draft_entries"]), 2)
        self.assertIn("sync_candidates", draft)
        self.assertIn("draft_entries", draft)
        self.assertIn("label_counts", draft)
        self.assertIn("readiness_counts", draft)

    def test_export_without_session_uses_latest_packet(self):
        packet_path = self.write_packet(
            "latest-session",
            turns=[
                {
                    "final_answers": ["Default workflow should inspect packet audit before promotion."],
                    "commands": ["`Bash` rg packet audit"],
                }
            ],
        )

        self.module.cmd_export(force=True)
        output_path = self.module.MEMORY_DRAFTS_DIR / "latest-session.json"
        self.assertTrue(output_path.exists())
        draft = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual("latest-session", draft["session_id"])

    def test_duplicate_candidate_texts_are_deduped(self):
        packet_path = self.write_packet(
            "dedupe-session",
            turns=[
                {
                    "assistant_updates": ["Default workflow should inspect packet audit before promotion."],
                    "final_answers": ["Default workflow should inspect packet audit before promotion."],
                    "commands": ["`Bash` rg packet audit"],
                }
            ],
        )

        draft = self.module.packet_to_draft(packet_path)

        self.assertEqual(1, len(draft["draft_entries"]))
        self.assertEqual(1, len(draft["sync_candidates"]))

    def test_partial_packet_blocks_sync_candidates(self):
        packet_path = self.write_packet(
            "partial-session",
            coverage="partial",
            warnings=["Detected compaction event."],
            turns=[
                {
                    "final_answers": ["Default workflow should inspect packet audit before promotion."],
                    "commands": ["`Bash` rg packet audit"],
                }
            ],
        )

        draft = self.module.packet_to_draft(packet_path)

        self.assertTrue(draft["requires_raw_review"])
        self.assertEqual([], draft["sync_candidates"])
        self.assertGreaterEqual(len(draft["blocked_sync_candidates"]), 1)
        self.assertGreaterEqual(draft["readiness_counts"].get("needs-raw-review", 0), 1)

    def test_existing_memory_can_mark_confirm(self):
        packet_path = self.write_packet(
            "confirm-session",
            turns=[
                {
                    "final_answers": ["Default workflow should inspect packet audit before promotion."],
                    "commands": ["`Bash` rg packet audit"],
                }
            ],
        )
        memory_path = self.home / "memory.json"
        memory_path.write_text(
            json.dumps(
                {
                    "observations": [
                        {"statement": "Default workflow should inspect packet audit before promotion."}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        draft = self.module.packet_to_draft(packet_path, memory_path=memory_path)

        self.assertIn("confirm", {entry["label"] for entry in draft["draft_entries"]})
        self.assertGreaterEqual(draft["label_counts"].get("confirm", 0), 1)

    def test_existing_memory_can_mark_refine(self):
        packet_path = self.write_packet(
            "refine-session",
            turns=[
                {
                    "final_answers": ["Default workflow should inspect packet audit before promoting auth workflow changes."],
                    "commands": ["`Bash` rg packet audit"],
                }
            ],
        )
        memory_path = self.home / "memory-refine.json"
        memory_path.write_text(
            json.dumps(
                {
                    "observations": [
                        {"statement": "Default workflow should inspect packet audit before promotion."}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        draft = self.module.packet_to_draft(packet_path, memory_path=memory_path)

        self.assertIn("refine", {entry["label"] for entry in draft["draft_entries"]})
        self.assertGreaterEqual(draft["label_counts"].get("refine", 0), 1)

    def test_existing_memory_can_mark_conflict(self):
        packet_path = self.write_packet(
            "conflict-session",
            turns=[
                {
                    "final_answers": ["Default workflow should not inspect packet audit before promotion."],
                    "commands": ["`Bash` rg packet audit"],
                }
            ],
        )
        memory_path = self.home / "memory-conflict.json"
        memory_path.write_text(
            json.dumps(
                {
                    "observations": [
                        {"statement": "Default workflow should inspect packet audit before promotion."}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        draft = self.module.packet_to_draft(packet_path, memory_path=memory_path)

        self.assertIn("conflict", {entry["label"] for entry in draft["draft_entries"]})
        self.assertGreaterEqual(len(draft["conflict_ids"]), 1)
        self.assertGreaterEqual(draft["readiness_counts"].get("needs-conflict-review", 0), 1)

    def test_ephemeral_entries_stay_local_only(self):
        packet_path = self.write_packet(
            "ephemeral-session",
            turns=[
                {
                    "final_answers": ["Need to use temporary session id 12345 for this one-off cleanup."],
                }
            ],
        )

        draft = self.module.packet_to_draft(packet_path)

        self.assertGreaterEqual(len(draft["local_only_ids"]), 1)
        self.assertEqual([], draft["sync_candidates"])
        self.assertIn("local-only", {entry["sync_readiness"] for entry in draft["draft_entries"]})

    def test_review_command_renders_readiness_sections(self):
        packet_path = self.write_packet(
            "review-session",
            turns=[
                {
                    "final_answers": ["Default workflow should inspect packet audit before promotion."],
                    "commands": ["`Bash` rg packet audit"],
                }
            ],
        )
        self.module.cmd_export(packet_path=str(packet_path), force=True)

        output = io.StringIO()
        with redirect_stdout(output):
            self.module.cmd_review(session_id="review-session")
        rendered = output.getvalue()

        self.assertIn("==> Review: review-session", rendered)
        self.assertIn("## ready-candidate", rendered)
        self.assertIn("statement: Default workflow should inspect packet audit before promotion.", rendered)

    def test_review_without_session_uses_latest_draft(self):
        packet_path = self.write_packet(
            "latest-review-session",
            turns=[
                {
                    "final_answers": ["Default workflow should inspect packet audit before promotion."],
                    "commands": ["`Bash` rg packet audit"],
                }
            ],
        )
        self.module.cmd_export(packet_path=str(packet_path), force=True)

        output = io.StringIO()
        with redirect_stdout(output):
            self.module.cmd_review()
        rendered = output.getvalue()

        self.assertIn("==> Review: latest-review-session", rendered)

    def test_approve_updates_review_status_and_counts(self):
        packet_path = self.write_packet(
            "approve-session",
            turns=[
                {
                    "final_answers": ["Default workflow should inspect packet audit before promotion."],
                    "commands": ["`Bash` rg packet audit"],
                }
            ],
        )
        self.module.cmd_export(packet_path=str(packet_path), force=True)
        draft_path = self.module.MEMORY_DRAFTS_DIR / "approve-session.json"
        draft = self.module.load_draft(draft_path)
        entry_id = draft["draft_entries"][0]["id"]

        self.module.cmd_update_review(action="approve", session_id="approve-session", entry_id=entry_id)

        refreshed = self.module.load_draft(draft_path)
        entry = refreshed["draft_entries"][0]
        self.assertEqual("approved", entry["review_status"])
        self.assertEqual(1, refreshed["review_counts"].get("approved", 0))
        self.assertEqual(0, refreshed["review_counts"].get("pending", 0))

    def test_note_appends_to_existing_review_note_and_log(self):
        packet_path = self.write_packet(
            "note-session",
            turns=[
                {
                    "final_answers": ["Default workflow should inspect packet audit before promotion."],
                    "commands": ["`Bash` rg packet audit"],
                }
            ],
        )
        self.module.cmd_export(packet_path=str(packet_path), force=True)
        draft_path = self.module.MEMORY_DRAFTS_DIR / "note-session.json"
        draft = self.module.load_draft(draft_path)
        entry_id = draft["draft_entries"][0]["id"]

        self.module.cmd_update_review(
            action="approve",
            session_id="note-session",
            entry_id=entry_id,
            note="looks stable",
        )
        self.module.cmd_update_review(
            action="note",
            session_id="note-session",
            entry_id=entry_id,
            note="sync after next project review",
        )

        refreshed = self.module.load_draft(draft_path)
        entry = refreshed["draft_entries"][0]
        self.assertEqual("approved", entry["review_status"])
        self.assertEqual(
            "looks stable\nsync after next project review",
            entry["review_note"],
        )
        self.assertEqual(2, len(entry["review_log"]))

    def test_approve_batch_uses_filters_and_generates_sync_list(self):
        packet_path = self.write_packet(
            "batch-session",
            turns=[
                {
                    "final_answers": [
                        "Default workflow should inspect packet audit before promotion.",
                        "Use rg auth.service when tracing authentication issues.",
                    ],
                    "commands": ["`Bash` rg auth.service"],
                    "referenced_files": ["packages/nestjs-server/src/modules/auth/auth.service.ts"],
                }
            ],
        )
        self.module.cmd_export(packet_path=str(packet_path), force=True)
        self.write_distilled_note("batch-session")

        self.module.cmd_batch_update_review(
            action="approve",
            session_id="batch-session",
            readiness="ready-candidate",
            review_status="pending",
        )

        draft_path = self.module.MEMORY_DRAFTS_DIR / "batch-session.json"
        refreshed = self.module.load_draft(draft_path)
        self.assertEqual(2, refreshed["review_counts"].get("approved", 0))
        sync_path = self.module.SYNC_LISTS_DIR / "batch-session.json"
        self.assertTrue(sync_path.exists())
        sync_payload = json.loads(sync_path.read_text(encoding="utf-8"))
        self.assertEqual(2, sync_payload["approved_ready_count"])

    def test_sync_list_is_removed_when_no_entries_remain_approved(self):
        packet_path = self.write_packet(
            "sync-removal-session",
            turns=[
                {
                    "final_answers": ["Default workflow should inspect packet audit before promotion."],
                    "commands": ["`Bash` rg packet audit"],
                }
            ],
        )
        self.module.cmd_export(packet_path=str(packet_path), force=True)
        self.write_distilled_note("sync-removal-session")
        draft_path = self.module.MEMORY_DRAFTS_DIR / "sync-removal-session.json"
        draft = self.module.load_draft(draft_path)
        entry_id = draft["draft_entries"][0]["id"]

        self.module.cmd_update_review(action="approve", session_id="sync-removal-session", entry_id=entry_id)
        sync_path = self.module.SYNC_LISTS_DIR / "sync-removal-session.json"
        self.assertTrue(sync_path.exists())

        self.module.cmd_update_review(
            action="reject",
            session_id="sync-removal-session",
            entry_id=entry_id,
            note="not stable enough",
        )
        self.assertFalse(sync_path.exists())

    def test_sync_list_blocked_without_final_review(self):
        packet_path = self.write_packet(
            "gate-session",
            turns=[{"final_answers": ["Default workflow should inspect packet audit before promotion."]}],
        )
        self.module.cmd_export(packet_path=str(packet_path), force=True)
        draft_path = self.module.MEMORY_DRAFTS_DIR / "gate-session.json"
        entry_id = self.module.load_draft(draft_path)["draft_entries"][0]["id"]
        self.module.cmd_update_review(action="approve", session_id="gate-session", entry_id=entry_id)
        sync_path = self.module.SYNC_LISTS_DIR / "gate-session.json"
        self.assertFalse(sync_path.exists())
        payload = self.module.build_sync_list(self.module.load_draft(draft_path), draft_path)
        self.assertFalse(payload["promotion_allowed"])
        self.assertTrue(payload["promotion_block_reasons"])

    def test_candidate_id_is_stable_across_export(self):
        turns = [{"final_answers": ["Default workflow should inspect packet audit before promotion."]}]
        first_path = self.write_packet("stable-session", turns=turns, revision_id="rev-stable")
        second_path = self.write_packet("stable-session", turns=turns, revision_id="rev-stable")
        first_draft = self.module.packet_to_draft(first_path, memory_path=None)
        second_draft = self.module.packet_to_draft(second_path, memory_path=None)
        self.assertEqual(first_draft["draft_entries"][0]["id"], second_draft["draft_entries"][0]["id"])
        self.assertNotEqual(first_draft["draft_entries"][0]["id"], "stable-session-1")

    def test_legacy_draft_is_hydrated_for_review(self):
        draft_path = self.module.MEMORY_DRAFTS_DIR / "legacy-session.json"
        draft_path.write_text(
            json.dumps(
                {
                    "session_id": "legacy-session",
                    "source_packet": "legacy.md",
                    "requires_raw_review": False,
                    "draft_entries": [
                        {
                            "id": "legacy-session-1",
                            "statement": "Default workflow should inspect packet audit before promotion.",
                            "label": "new",
                            "destination": "project-rules",
                            "rationale": "legacy draft",
                            "evidence_refs": {"turn_number": 1, "source_kind": "final_answers"},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        output = io.StringIO()
        with redirect_stdout(output):
            self.module.cmd_review(session_id="legacy-session")
        rendered = output.getvalue()

        self.assertIn("## ready-candidate", rendered)
        self.assertIn("Label counts:", rendered)


if __name__ == "__main__":
    unittest.main()
