import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.distill_core.base_adapter import BasePlatformAdapter


class DummyAdapter(BasePlatformAdapter):
    def index(self, project_filter: str | None = None) -> int:
        manifest = self.load_manifest()
        session_entry = {
            "session_id": "test-session-1",
            "project": "servers",
            "status": "new",
            "last_write_time": "2026-09-24T00:00:00Z",
            "size_bytes": 100,
        }
        self.upsert_session_in_manifest(manifest, session_entry)
        self.save_manifest(manifest)
        return 1

    def parse_session_turns(self, session_entry: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "turn_id": "turn-1",
                "user_messages": ["hello"],
                "assistant_updates": ["world"],
                "final_answers": ["done"],
                "plans": [],
                "patches": [],
                "commands": [],
                "command_outputs": [],
                "system_events": [],
            }
        ]


class TestBasePlatformAdapter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.distill_dir = Path(self.temp_dir.name)
        self.adapter = DummyAdapter("dummy", self.distill_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ensure_dirs_and_manifest(self):
        self.adapter.ensure_dirs()
        self.assertTrue(self.adapter.manifest_file.exists())
        self.assertTrue(self.adapter.knowledge_file.exists())
        self.assertTrue(self.adapter.packets_dir.exists())
        self.assertTrue(self.adapter.distilled_dir.exists())
        self.assertTrue(self.adapter.answer_packets_dir.exists())

        manifest = self.adapter.load_manifest()
        self.assertEqual(manifest.get("version"), 1)
        self.assertEqual(manifest.get("sessions"), [])

    def test_index_and_stats(self):
        self.adapter.ensure_dirs()
        indexed = self.adapter.index()
        self.assertEqual(indexed, 1)

        stats = self.adapter.get_summary_stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["bundled"], 0)

    def test_project_filtering(self):
        sessions = [
            {"session_id": "s1", "project": "servers/backend"},
            {"session_id": "s2", "project": "front/web"},
            {"session_id": "s3", "workspace": "/data/workspaces/servers"},
        ]
        filtered = self.adapter.filter_sessions_by_project(sessions, "servers")
        self.assertEqual(len(filtered), 2)
        self.assertEqual({s["session_id"] for s in filtered}, {"s1", "s3"})


if __name__ == "__main__":
    unittest.main()
