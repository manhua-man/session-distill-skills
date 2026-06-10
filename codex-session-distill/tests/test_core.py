import importlib.util
import json
import io
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "session-distill.py"


def load_module():
    spec = importlib.util.spec_from_file_location("codex_session_distill", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CodexSessionDistillTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.module = load_module()
        self.module.CODEX_HOME = self.home / ".codex"
        self.module.DISTILL_DIR = self.module.CODEX_HOME / "session-distill"
        self.module.MANIFEST_FILE = self.module.DISTILL_DIR / "manifest.json"
        self.module.KNOWLEDGE_FILE = self.module.DISTILL_DIR / "knowledge-base.md"
        self.module.PACKETS_DIR = self.module.DISTILL_DIR / "packets"
        self.module.DISTILLED_DIR = self.module.DISTILL_DIR / "distilled" / "sessions"
        self.module.MEMORY_DRAFTS_DIR = self.module.DISTILL_DIR / "memory-drafts"
        self.module.ARCHIVED_DIR = self.module.CODEX_HOME / "archived_sessions"
        self.module.LIVE_SESSIONS_DIR = self.module.CODEX_HOME / "sessions"
        self.module.SESSION_INDEX_FILE = self.module.CODEX_HOME / "session_index.jsonl"
        self.module.ARCHIVED_DIR.mkdir(parents=True, exist_ok=True)
        self.module.ensure_dirs()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_session(self, session_id="019e0000-0000-7000-8000-000000000001", records=None):
        path = self.module.ARCHIVED_DIR / f"rollout-2026-01-01T00-00-00-{session_id}.jsonl"
        records = records or [
            {"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta", "payload": {"id": session_id, "cwd": "E:/repo", "source": "vscode"}},
            {"timestamp": "2026-01-01T00:00:01Z", "type": "turn_context", "payload": {"turn_id": "turn-1", "cwd": "E:/repo"}},
            {"timestamp": "2026-01-01T00:00:02Z", "type": "event_msg", "payload": {"type": "user_message", "message": "整理一下对话"}},
            {"timestamp": "2026-01-01T00:00:03Z", "type": "event_msg", "payload": {"type": "agent_message", "message": "我先读取 packet。", "phase": "commentary"}},
            {"timestamp": "2026-01-01T00:00:04Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final_answer", "content": [{"type": "output_text", "text": "完成。"}]}},
        ]
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    def test_packet_contains_codex_turn_content(self):
        self.write_session()
        self.module.cmd_run(next_count=1, force=False)
        packet = next(self.module.PACKETS_DIR.glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("整理一下对话", packet)
        self.assertIn("我先读取 packet", packet)
        self.assertIn("完成。", packet)
        self.assertIn("Coverage: `high`", packet)

    def test_long_output_marks_partial(self):
        session_id = "019e0000-0000-7000-8000-000000000002"
        records = [
            {"type": "session_meta", "payload": {"id": session_id}},
            {"type": "turn_context", "payload": {"turn_id": "turn-1"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "x" * 3000}},
        ]
        self.write_session(session_id=session_id, records=records)
        self.module.cmd_run(next_count=1, force=False)
        packet = (self.module.PACKETS_DIR / f"{session_id}.md").read_text(encoding="utf-8")
        self.assertIn("Coverage: `partial`", packet)
        self.assertIn("command output excerpt", packet)

    def test_ide_context_is_trimmed_and_agents_context_is_ignored(self):
        session_id = "019e0000-0000-7000-8000-000000000004"
        records = [
            {"type": "session_meta", "payload": {"id": session_id}},
            {"type": "turn_context", "payload": {"turn_id": "turn-1"}},
            {
                "type": "event_msg",
                "payload": {
                    "type": "user_message",
                    "message": "# AGENTS.md instructions for e:\\project\\servers\n\n<INSTRUCTIONS>\nnoise\n</INSTRUCTIONS>",
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "user_message",
                    "message": "# Context from my IDE setup:\n\n## Active file: app.ts\n\n## My request for Codex:\n真正的用户请求",
                },
            },
        ]
        self.write_session(session_id=session_id, records=records)
        self.module.cmd_run(next_count=1, force=False)
        packet = (self.module.PACKETS_DIR / f"{session_id}.md").read_text(encoding="utf-8")
        self.assertIn("真正的用户请求", packet)
        self.assertNotIn("AGENTS.md instructions", packet)
        self.assertNotIn("Active file", packet)
        self.assertIn("Ignored Context Messages: 1", packet)
        self.assertIn("Trimmed Context Messages: 1", packet)

    def test_mark_distilled_requires_note(self):
        session_id = "019e0000-0000-7000-8000-000000000003"
        raw_path = self.write_session(session_id=session_id)
        self.module.cmd_run(next_count=1, force=False)
        self.assertEqual(self.module.cmd_mark(session_id, "distilled"), 1)
        note = self.module.DISTILLED_DIR / f"{session_id}.md"
        note.write_text("# Note\n\n## Promotion Decision\n\nNo Promotion. raw transcript reviewed.\n", encoding="utf-8")
        self.assertEqual(self.module.cmd_mark(session_id, "distilled"), 0)
        self.assertFalse(raw_path.exists())

    def test_distilled_missing_raw_is_preserved_on_reindex(self):
        session_id = "019e0000-0000-7000-8000-000000000007"
        raw_path = self.write_session(session_id=session_id)
        self.module.cmd_run(next_count=1, force=False)
        note = self.module.DISTILLED_DIR / f"{session_id}.md"
        note.write_text("# Note\n\n## Promotion Decision\n\nNo Promotion. raw transcript reviewed.\n", encoding="utf-8")
        self.assertEqual(self.module.cmd_mark(session_id, "distilled"), 0)
        self.assertFalse(raw_path.exists())
        self.module.cmd_index()
        manifest = self.module.load_manifest()
        matching = [session for session in manifest["sessions"] if session["session_id"] == session_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["status"], "distilled")
        self.assertTrue(matching[0]["source_missing"])

    def test_keep_raw_preserves_source_file_after_mark(self):
        session_id = "019e0000-0000-7000-8000-000000000008"
        raw_path = self.write_session(session_id=session_id)
        self.module.cmd_run(next_count=1, force=False)
        note = self.module.DISTILLED_DIR / f"{session_id}.md"
        note.write_text("# Note\n\n## Promotion Decision\n\nNo Promotion. raw transcript reviewed.\n", encoding="utf-8")
        self.assertEqual(self.module.cmd_mark(session_id, "distilled", keep_raw=True), 0)
        self.assertTrue(raw_path.exists())

    def test_prune_removes_source_missing_processed_records_only(self):
        kept_id = "019e0000-0000-7000-8000-000000000009"
        pruned_id = "019e0000-0000-7000-8000-000000000010"
        self.write_session(session_id=kept_id)
        self.write_session(session_id=pruned_id)
        self.module.cmd_index()
        manifest = self.module.load_manifest()
        for session in manifest["sessions"]:
            if session["session_id"] == kept_id:
                session["status"] = "new"
            if session["session_id"] == pruned_id:
                session["status"] = "distilled"
                session["source_missing"] = True
                session["raw_deleted_at"] = "2026-01-01T00:00:00Z"
        self.module.save_manifest(manifest)
        self.assertEqual(self.module.cmd_prune(), 0)
        manifest = self.module.load_manifest()
        ids = {session["session_id"] for session in manifest["sessions"]}
        self.assertIn(kept_id, ids)
        self.assertNotIn(pruned_id, ids)

    def test_force_bundle_does_not_reopen_distilled_sessions(self):
        distilled_id = "019e0000-0000-7000-8000-000000000005"
        new_id = "019e0000-0000-7000-8000-000000000006"
        self.write_session(session_id=distilled_id)
        self.write_session(session_id=new_id)
        self.module.cmd_index()
        manifest = self.module.load_manifest()
        for session in manifest["sessions"]:
            if session["session_id"] == distilled_id:
                session["status"] = "distilled"
        self.module.save_manifest(manifest)
        self.module.cmd_bundle(next_count=10, force=True)
        manifest = self.module.load_manifest()
        statuses = {session["session_id"]: session["status"] for session in manifest["sessions"]}
        self.assertEqual(statuses[distilled_id], "distilled")
        self.assertEqual(statuses[new_id], "bundled")

    def test_load_kb_entries_and_review_status(self):
        session_id = "019e0000-0000-7000-8000-000000000011"
        self.write_session(session_id=session_id)
        self.module.cmd_run(next_count=1, force=False)
        note = self.module.DISTILLED_DIR / f"{session_id}.md"
        note.write_text(
            (
                f"# Session Distillation: {session_id}\n\n"
                "## Promotion Decision\n\n"
                "Promote:\n\n"
                "- When adding a new workflow rule, verify it against code and config.\n"
            ),
            encoding="utf-8",
        )
        self.module.KNOWLEDGE_FILE.write_text(
            (
                "# Archived Session Knowledge Base\n\n"
                "## Stable Workflows\n\n"
                f"- `code`: When adding a new workflow rule, verify it against code and config. Source: `{session_id}`.\n"
            ),
            encoding="utf-8",
        )
        entries = self.module.load_kb_entries()
        self.assertEqual(len(entries), 1)
        status, reasons = self.module.assess_kb_entry(entries[0], current_session_id=session_id)
        self.assertEqual(status, "stable")
        self.assertEqual(reasons, [])

    def test_mark_distilled_fails_when_kb_entry_needs_review(self):
        session_id = "019e0000-0000-7000-8000-000000000012"
        self.write_session(session_id=session_id)
        self.module.cmd_run(next_count=1, force=False)
        note = self.module.DISTILLED_DIR / f"{session_id}.md"
        note.write_text(
            (
                f"# Session Distillation: {session_id}\n\n"
                "## Raw Review\n\n"
                "raw JSONL reviewed.\n\n"
                "## Promotion Decision\n\n"
                "Promote:\n\n"
                "- 临时端口 workaround.\n"
            ),
            encoding="utf-8",
        )
        self.module.KNOWLEDGE_FILE.write_text(
            (
                "# Archived Session Knowledge Base\n\n"
                "## Stable Workflows\n\n"
                f"- `tooling`: 临时端口 workaround. Source: `{session_id}`.\n"
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.module.cmd_mark(session_id, "distilled"), 1)

    def test_prune_kb_removes_stale_entries(self):
        missing_session_id = "019e0000-0000-7000-8000-000000000013"
        self.module.KNOWLEDGE_FILE.write_text(
            (
                "# Archived Session Knowledge Base\n\n"
                "## Stable Workflows\n\n"
                f"- `tooling`: When something changes, verify it twice. Source: `{missing_session_id}`.\n"
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.module.cmd_prune_kb(), 0)
        text = self.module.KNOWLEDGE_FILE.read_text(encoding="utf-8")
        self.assertNotIn(missing_session_id, text)

    def test_review_kb_reports_needs_review(self):
        session_id = "019e0000-0000-7000-8000-000000000014"
        self.write_session(session_id=session_id)
        self.module.cmd_run(next_count=1, force=False)
        note = self.module.DISTILLED_DIR / f"{session_id}.md"
        note.write_text(
            (
                f"# Session Distillation: {session_id}\n\n"
                "## Promotion Decision\n\n"
                "Promote:\n\n"
                "- short note\n"
            ),
            encoding="utf-8",
        )
        self.module.KNOWLEDGE_FILE.write_text(
            (
                "# Archived Session Knowledge Base\n\n"
                "## Stable Workflows\n\n"
                f"- `tooling`: 临时 workaround. Source: `{session_id}`.\n"
            ),
            encoding="utf-8",
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(self.module.cmd_review_kb(limit=10), 0)
        output = buffer.getvalue()
        self.assertIn("[needs-review]", output)

    def test_review_kb_updates_review_state(self):
        session_id = "019e0000-0000-7000-8000-000000000015"
        self.write_session(session_id=session_id)
        self.module.cmd_run(next_count=1, force=False)
        note = self.module.DISTILLED_DIR / f"{session_id}.md"
        note.write_text(
            (
                f"# Session Distillation: {session_id}\n\n"
                "## Promotion Decision\n\n"
                "Promote:\n\n"
                "- When a workflow changes, verify code and config together.\n"
            ),
            encoding="utf-8",
        )
        self.module.KNOWLEDGE_FILE.write_text(
            (
                "# Archived Session Knowledge Base\n\n"
                "## Stable Workflows\n\n"
                f"- `code`: When a workflow changes, verify code and config together. Source: `{session_id}`.\n"
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.module.cmd_review_kb(limit=10), 0)
        state = self.module.load_kb_review_state()
        self.assertEqual(state["last_reviewed_entry_count"], 1)
        self.assertTrue(state["last_reviewed_at"])

    def test_bundle_and_mark_emit_kb_reminders(self):
        old_session_id = "019e0000-0000-7000-8000-000000000016"
        new_session_id = "019e0000-0000-7000-8000-000000000017"
        self.write_session(session_id=old_session_id)
        self.module.cmd_run(next_count=1, force=False)
        old_note = self.module.DISTILLED_DIR / f"{old_session_id}.md"
        old_note.write_text(
            (
                f"# Session Distillation: {old_session_id}\n\n"
                "## Promotion Decision\n\n"
                "Promote:\n\n"
                "- When gameplay stats change, verify cloud-save registration and local persistence together.\n"
            ),
            encoding="utf-8",
        )
        self.module.KNOWLEDGE_FILE.write_text(
            (
                "# Archived Session Knowledge Base\n\n"
                "## Stable Workflows\n\n"
                f"- `code`: When gameplay stats change, verify cloud-save registration and local persistence together. Source: `{old_session_id}`.\n"
            ),
            encoding="utf-8",
        )
        self.module.save_kb_review_state({"last_reviewed_entry_count": -10, "last_reviewed_at": ""})

        records = [
            {"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta", "payload": {"id": new_session_id, "cwd": "E:/repo", "source": "vscode"}},
            {"timestamp": "2026-01-01T00:00:01Z", "type": "turn_context", "payload": {"turn_id": "turn-1", "cwd": "E:/repo"}},
            {"timestamp": "2026-01-01T00:00:02Z", "type": "event_msg", "payload": {"type": "user_message", "message": "检查 gameplay stats 和 cloud-save registration"}},
            {"timestamp": "2026-01-01T00:00:03Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final_answer", "content": [{"type": "output_text", "text": "完成。"}]}},
        ]
        self.write_session(session_id=new_session_id, records=records)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.module.cmd_run(next_count=1, force=False)
        output = buffer.getvalue()
        self.assertIn("Knowledge Verify Reminder", output)

        new_note = self.module.DISTILLED_DIR / f"{new_session_id}.md"
        new_note.write_text(
            (
                f"# Session Distillation: {new_session_id}\n\n"
                "## Promotion Decision\n\n"
                "Promote:\n\n"
                "- When gameplay stats change, verify cloud-save registration and local persistence together.\n"
            ),
            encoding="utf-8",
        )
        self.module.KNOWLEDGE_FILE.write_text(
            self.module.KNOWLEDGE_FILE.read_text(encoding="utf-8")
            + f"- `code`: When gameplay stats change, verify cloud-save registration and local persistence together. Source: `{new_session_id}`.\n",
            encoding="utf-8",
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.module.cmd_mark(new_session_id, "distilled")
        output = buffer.getvalue()
        self.assertIn("Knowledge Review Reminder", output)


if __name__ == "__main__":
    unittest.main()
