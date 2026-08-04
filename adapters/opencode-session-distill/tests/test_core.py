import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from note_fixtures import distilled_note


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "opencode-session-distill.py"


def load_module():
    spec = importlib.util.spec_from_file_location("opencode_session_distill", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OpenCodeSessionDistillTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.module = load_module()
        self.module.OPENCODE_HOME = self.home / ".local" / "share" / "opencode"
        self.module.STORAGE_DIR = self.module.OPENCODE_HOME / "storage"
        self.module.DISTILL_DIR = self.module.OPENCODE_HOME / "session-distill"
        self.module.MANIFEST_FILE = self.module.DISTILL_DIR / "manifest.json"
        self.module.KNOWLEDGE_FILE = self.module.DISTILL_DIR / "knowledge-base.md"
        self.module.PACKETS_DIR = self.module.DISTILL_DIR / "packets"
        self.module.DISTILLED_DIR = self.module.DISTILL_DIR / "distilled" / "sessions"
        self.module.ensure_dirs()
        self._write_session("opencode-session-1", "E:/project/servers")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_session(self, session_id: str, project_path: str) -> None:
        project_key = "servers"
        session_dir = self.module.STORAGE_DIR / "session" / project_key
        session_dir.mkdir(parents=True, exist_ok=True)
        session_path = session_dir / f"{session_id}.json"
        session_path.write_text(
            json.dumps(
                {
                    "id": session_id,
                    "title": "整理 OpenCode 对话",
                    "directory": project_path,
                    "time": {"created": "2026-07-15T00:00:00Z"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        message_dir = self.module.STORAGE_DIR / "message" / session_id
        message_dir.mkdir(parents=True, exist_ok=True)
        messages = [
            ("msg-1", "user", "整理一下 OpenCode 对话"),
            ("msg-2", "assistant", "我先读取 packet。"),
            ("msg-3", "assistant", "完成。"),
        ]
        for message_id, role, text in messages:
            self._write_message(session_id, message_id, role, text)

    def _write_message(self, session_id: str, message_id: str, role: str, text: str) -> None:
        message_dir = self.module.STORAGE_DIR / "message" / session_id
        message_dir.mkdir(parents=True, exist_ok=True)
        (message_dir / f"{message_id}.json").write_text(
            json.dumps({"id": message_id, "role": role}, ensure_ascii=False),
            encoding="utf-8",
        )
        part_dir = self.module.STORAGE_DIR / "part" / message_id
        part_dir.mkdir(parents=True, exist_ok=True)
        (part_dir / "part-1.json").write_text(
            json.dumps({"text": text}, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_packet_contains_opencode_turn_content(self):
        self.module.cmd_index(project_filter="servers")
        self.module.cmd_bundle(next_count=1, force=False)
        packet = (self.module.PACKETS_DIR / "opencode-session-1.md").read_text(encoding="utf-8")
        self.assertIn("整理一下 OpenCode 对话", packet)
        self.assertIn("我先读取 packet", packet)
        self.assertIn("Coverage: `lossless`", packet)

    def test_mark_distilled_requires_final_review(self):
        session_id = "opencode-session-1"
        self.module.cmd_index(project_filter="servers")
        self.module.cmd_bundle(next_count=1, force=False)
        self.assertEqual(self.module.cmd_mark(session_id, "distilled"), 1)
        note = self.module.DISTILLED_DIR / f"{session_id}.md"
        note.write_text(distilled_note(), encoding="utf-8")
        self.assertEqual(self.module.cmd_mark(session_id, "distilled"), 0)

    def test_distilled_session_requeues_when_message_tree_grows(self):
        session_id = "opencode-session-1"
        self.module.cmd_index(project_filter="servers")
        self.module.cmd_bundle(next_count=1, force=False)
        note = self.module.DISTILLED_DIR / f"{session_id}.md"
        note.write_text(distilled_note(), encoding="utf-8")
        self.assertEqual(self.module.cmd_mark(session_id, "distilled"), 0)

        self._write_message(session_id, "msg-4", "assistant", "新增的最终答案。")
        self.module.cmd_index(project_filter="servers")
        session = self.module.load_manifest()["sessions"][0]
        self.assertEqual(session["status"], "pending_redistill")

        self.module.cmd_bundle(next_count=1, force=False)
        packet = (self.module.PACKETS_DIR / f"{session_id}.md").read_text(encoding="utf-8")
        self.assertIn("新增的最终答案", packet)
