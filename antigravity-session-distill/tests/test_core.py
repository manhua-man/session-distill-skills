import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from note_fixtures import distilled_note


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "antigravity-session-distill.py"


def load_module():
    spec = importlib.util.spec_from_file_location("antigravity_session_distill", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AntigravitySessionDistillTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.module = load_module()
        self.module.AGY_HOME = self.home / "antigravity-cli"
        self.module.AGY_HOME.mkdir(parents=True, exist_ok=True)
        self.module.DISTILL_DIR = self.home / "antigravity-cli" / "session-distill"
        self.module.MANIFEST_FILE = self.module.DISTILL_DIR / "manifest.json"
        self.module.KNOWLEDGE_FILE = self.module.DISTILL_DIR / "knowledge-base.md"
        self.module.PACKETS_DIR = self.module.DISTILL_DIR / "packets"
        self.module.DISTILLED_DIR = self.module.DISTILL_DIR / "distilled" / "sessions"
        self.module.HISTORY_FILE = self.module.AGY_HOME / "history.jsonl"
        self.module.BRAIN_DIR = self.module.AGY_HOME / "brain"
        self.module.ensure_dirs()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_history(self, session_id="conv-agy-1", prompt="整理 Antigravity 对话"):
        record = {
            "conversationId": session_id,
            "workspace": "E:/project/servers",
            "display": prompt,
            "timestamp": 1_700_000_000_000,
        }
        with self.module.HISTORY_FILE.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def test_packet_contains_history_prompt(self):
        self.write_history()
        self.module.cmd_index(project_filter="servers")
        self.module.cmd_bundle(next_count=1, force=False)
        packet = (self.module.PACKETS_DIR / "conv-agy-1.md").read_text(encoding="utf-8")
        self.assertIn("整理 Antigravity 对话", packet)
        self.assertIn("Coverage: `lossless`", packet)

    def test_mark_distilled_requires_note(self):
        self.write_history()
        self.module.cmd_index(project_filter="servers")
        self.module.cmd_bundle(next_count=1, force=False)
        self.assertEqual(self.module.cmd_mark("conv-agy-1", "distilled"), 1)
        note = self.module.DISTILLED_DIR / "conv-agy-1.md"
        note.write_text(distilled_note(), encoding="utf-8")
        self.assertEqual(self.module.cmd_mark("conv-agy-1", "distilled"), 0)


if __name__ == "__main__":
    unittest.main()
