from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CLEANUP_SCRIPT = REPO_ROOT / "adapters" / "antigravity-session-distill" / "bin" / "cleanup-antigravity-distill.py"

import importlib.util

spec = importlib.util.spec_from_file_location("antigravity_cleanup", str(CLEANUP_SCRIPT))
cleanup_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup_mod)


class TestAntigravityCleanup(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_clean_app_storage(self):
        storage_file = self.test_root / "app_storage.json"
        target_sid = "11111111-2222-3333-4444-555555555555"
        keep_sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        initial_data = {
            f"antigravity-multi-conversation-layout-v3-{target_sid}": {"focusedPaneId": "p1"},
            f"antigravity-multi-conversation-layout-v3-{keep_sid}": {"focusedPaneId": "p2"},
            "aux-pane-session": json.dumps({
                "conversationPanes": {
                    target_sid: {"tabs": [{"id": "tab1"}]},
                    keep_sid: {"tabs": [{"id": "tab2"}]},
                }
            }),
            "comments": json.dumps({
                "artifacts": {
                    f"file:///C:/path/brain/{target_sid}/plan.md": {"comments": []},
                    f"file:///C:/path/brain/{keep_sid}/plan.md": {"comments": []},
                }
            }),
            "pinned_conversations_order": json.dumps([keep_sid]),
        }
        storage_file.write_text(json.dumps(initial_data), encoding="utf-8")

        with patch.object(cleanup_mod, "resolve_app_storage_path", return_value=storage_file):
            removed = cleanup_mod.clean_app_storage([target_sid], dry_run=False)

        self.assertGreater(removed, 0)

        updated = json.loads(storage_file.read_text(encoding="utf-8"))
        self.assertNotIn(f"antigravity-multi-conversation-layout-v3-{target_sid}", updated)
        self.assertIn(f"antigravity-multi-conversation-layout-v3-{keep_sid}", updated)

        aux = json.loads(updated["aux-pane-session"])
        self.assertNotIn(target_sid, aux["conversationPanes"])
        self.assertIn(keep_sid, aux["conversationPanes"])

        comments = json.loads(updated["comments"])
        self.assertNotIn(f"file:///C:/path/brain/{target_sid}/plan.md", comments["artifacts"])
        self.assertIn(f"file:///C:/path/brain/{keep_sid}/plan.md", comments["artifacts"])

    def test_get_distilled_session_ids(self):
        distill_dir = self.test_root / "session-distill"
        distill_dir.mkdir(parents=True)
        manifest_file = distill_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps({
                "sessions": {
                    "s-1": {"status": "distilled"},
                    "s-2": {"status": "pending"},
                    "s-3": {"status": "distilled"},
                }
            }),
            encoding="utf-8",
        )

        ids = cleanup_mod.get_distilled_session_ids(distill_dir)
        self.assertEqual(ids, {"s-1", "s-3"})

    def test_cleanup_distill_workspace_dry_run(self):
        distill_dir = self.test_root / "session-distill"
        packets_dir = distill_dir / "packets"
        packets_dir.mkdir(parents=True)
        (packets_dir / "s-1.md").write_text("dummy", encoding="utf-8")

        manifest_file = distill_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps({"sessions": {"s-1": {"status": "distilled"}}}),
            encoding="utf-8",
        )

        ret = cleanup_mod.cleanup_distill_workspace(
            "packets",
            distill_dir=distill_dir,
            dry_run=True,
        )
        self.assertEqual(ret, 0)
        self.assertTrue((packets_dir / "s-1.md").exists())


if __name__ == "__main__":
    unittest.main()
