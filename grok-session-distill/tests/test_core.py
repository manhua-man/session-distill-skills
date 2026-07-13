import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "grok-session-distill.py"


def load_module():
    spec = importlib.util.spec_from_file_location("grok_session_distill", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GrokSessionDistillTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.module = load_module()
        self.module.GROK_HOME = self.home / ".grok"
        self.module.SESSIONS_ROOT = self.module.GROK_HOME / "sessions"
        self.module.DISTILL_DIR = self.module.GROK_HOME / "session-distill"
        self.module.MANIFEST_FILE = self.module.DISTILL_DIR / "manifest.json"
        self.module.KNOWLEDGE_FILE = self.module.DISTILL_DIR / "knowledge-base.md"
        self.module.PACKETS_DIR = self.module.DISTILL_DIR / "packets"
        self.module.DISTILLED_DIR = self.module.DISTILL_DIR / "distilled" / "sessions"
        self.module.ensure_dirs()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_session(
        self,
        session_id="019f5a00-00cd-7850-806e-56fc56494a5c",
        project_path="E:/project/servers",
        records=None,
        summary=None,
    ):
        encoded = self.module.encode_project_path(project_path)
        session_dir = self.module.SESSIONS_ROOT / encoded / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        chat_history = session_dir / "chat_history.jsonl"
        records = records or [
            {"type": "system", "content": "system prompt"},
            {
                "type": "user",
                "content": [{"type": "text", "text": "<user_query>\n整理一下 Grok 对话\n</user_query>"}],
            },
            {"type": "assistant", "content": "我先读取 packet。", "tool_calls": []},
            {
                "type": "tool_result",
                "tool_call_id": "call-1",
                "content": "packet ready",
            },
            {"type": "assistant", "content": "完成。", "tool_calls": []},
        ]
        with chat_history.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        summary = summary or {
            "info": {"id": session_id, "cwd": project_path},
            "generated_title": "整理 Grok 对话",
            "created_at": "2026-07-13T05:42:57.504693500Z",
            "current_model_id": "grok-composer-2.5-fast",
            "head_branch": "main",
        }
        (session_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return chat_history, session_dir

    def test_packet_contains_grok_turn_content(self):
        self.write_session()
        self.module.cmd_run(next_count=1, force=False)
        packet = next(self.module.PACKETS_DIR.glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("整理一下 Grok 对话", packet)
        self.assertIn("我先读取 packet", packet)
        self.assertIn("完成。", packet)
        self.assertIn("Coverage: `high`", packet)

    def test_context_message_is_trimmed(self):
        session_id = "019f5a00-00cd-7850-806e-56fc56494a5d"
        records = [
            {
                "type": "user",
                "content": [{"type": "text", "text": "<user_info>\nnoise\n</user_info>\n<user_query>\n真正的用户请求\n</user_query>"}],
            },
        ]
        self.write_session(session_id=session_id, records=records)
        self.module.cmd_run(next_count=1, force=False)
        packet = (self.module.PACKETS_DIR / f"{session_id}.md").read_text(encoding="utf-8")
        self.assertIn("真正的用户请求", packet)
        self.assertNotIn("<user_info>", packet)
        self.assertIn("Trimmed Context Messages: 1", packet)

    def test_long_output_marks_partial(self):
        session_id = "019f5a00-00cd-7850-806e-56fc56494a5e"
        records = [
            {"type": "user", "content": [{"type": "text", "text": "<user_query>\n跑一下命令\n</user_query>"}]},
            {"type": "tool_result", "tool_call_id": "call-1", "content": "x" * 35000},
        ]
        self.write_session(session_id=session_id, records=records)
        self.module.cmd_run(next_count=1, force=False)
        packet = (self.module.PACKETS_DIR / f"{session_id}.md").read_text(encoding="utf-8")
        self.assertIn("Coverage: `partial`", packet)
        self.assertIn("command output excerpt", packet)

    def test_mark_distilled_requires_note(self):
        session_id = "019f5a00-00cd-7850-806e-56fc56494a5f"
        chat_history, _ = self.write_session(session_id=session_id)
        self.module.cmd_run(next_count=1, force=False)
        self.assertEqual(self.module.cmd_mark(session_id, "distilled"), 1)
        note = self.module.DISTILLED_DIR / f"{session_id}.md"
        note.write_text(
            "# Note\n\n## Promotion Decision\n\nNo Promotion. chat_history reviewed.\n",
            encoding="utf-8",
        )
        self.assertEqual(self.module.cmd_mark(session_id, "distilled"), 0)
        self.assertTrue(chat_history.exists())

    def test_delete_raw_removes_chat_history(self):
        session_id = "019f5a00-00cd-7850-806e-56fc56494a60"
        chat_history, _ = self.write_session(session_id=session_id)
        self.module.cmd_run(next_count=1, force=False)
        note = self.module.DISTILLED_DIR / f"{session_id}.md"
        note.write_text(
            "# Note\n\n## Promotion Decision\n\nNo Promotion. chat_history reviewed.\n",
            encoding="utf-8",
        )
        self.assertEqual(self.module.cmd_mark(session_id, "distilled", delete_raw=True), 0)
        self.assertFalse(chat_history.exists())

    def test_project_filter_limits_index(self):
        self.write_session(session_id="019f5a00-00cd-7850-806e-56fc56494a61", project_path="E:/project/servers")
        self.write_session(session_id="019f5a00-00cd-7850-806e-56fc56494a62", project_path="E:/project/code")
        self.module.cmd_index(project_filter="servers")
        manifest = self.module.load_manifest()
        ids = {session["session_id"] for session in manifest["sessions"]}
        self.assertIn("019f5a00-00cd-7850-806e-56fc56494a61", ids)
        self.assertNotIn("019f5a00-00cd-7850-806e-56fc56494a62", ids)


if __name__ == "__main__":
    unittest.main()