import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from note_fixtures import distilled_note


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "hermes-session-distill.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_session_distill", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HermesSessionDistillTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.module = load_module()
        self.module.HERMES_HOME = self.home / "hermes"
        self.module.HERMES_HOME.mkdir(parents=True, exist_ok=True)
        self.module.DISTILL_DIR = self.home / "hermes" / "session-distill"
        self.module.MANIFEST_FILE = self.module.DISTILL_DIR / "manifest.json"
        self.module.KNOWLEDGE_FILE = self.module.DISTILL_DIR / "knowledge-base.md"
        self.module.PACKETS_DIR = self.module.DISTILL_DIR / "packets"
        self.module.DISTILLED_DIR = self.module.DISTILL_DIR / "distilled" / "sessions"
        self.db_path = self.module.HERMES_HOME / "state.db"
        self._create_db()
        self.module.ensure_dirs()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                source TEXT,
                started_at REAL,
                ended_at REAL,
                message_count INTEGER,
                cwd TEXT,
                git_repo_root TEXT,
                model TEXT,
                archived INTEGER DEFAULT 0
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                tool_name TEXT,
                active INTEGER DEFAULT 1
            );
            """
        )
        conn.execute(
            """
            INSERT INTO sessions (id, title, source, started_at, ended_at, message_count, cwd, git_repo_root, model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "hermes-session-1",
                "整理 Hermes 对话",
                "cli",
                1_700_000_000.0,
                1_700_000_100.0,
                3,
                "servers",
                "servers",
                "hermes-test",
            ),
        )
        for role, content, tool_name in (
            ("user", "<user_query>\n整理一下 Hermes 对话\n</user_query>", ""),
            ("assistant", "我先读取 packet。", ""),
            ("tool", "packet ready", "read_file"),
            ("assistant", "完成。", ""),
        ):
            conn.execute(
                "INSERT INTO messages (session_id, role, content, tool_name) VALUES (?, ?, ?, ?)",
                ("hermes-session-1", role, content, tool_name),
            )
        conn.commit()
        conn.close()

    def test_packet_contains_hermes_turn_content(self):
        self.module.cmd_index(project_filter="servers")
        self.module.cmd_bundle(next_count=1, force=False)
        packet = (self.module.PACKETS_DIR / "hermes-session-1.md").read_text(encoding="utf-8")
        self.assertIn("整理一下 Hermes 对话", packet)
        self.assertIn("我先读取 packet", packet)
        self.assertIn("Coverage: `lossless`", packet)

    def test_mark_distilled_requires_note(self):
        self.module.cmd_index(project_filter="servers")
        self.module.cmd_bundle(next_count=1, force=False)
        self.assertEqual(self.module.cmd_mark("hermes-session-1", "distilled"), 1)
        note = self.module.DISTILLED_DIR / "hermes-session-1.md"
        note.write_text(distilled_note(), encoding="utf-8")
        self.assertEqual(self.module.cmd_mark("hermes-session-1", "distilled"), 0)


if __name__ == "__main__":
    unittest.main()
