#!/usr/bin/env python3
"""Verify shared distill artifacts match canonical install across platform bins."""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

CANONICAL_BIN = Path(__file__).resolve().parents[1] / "bin"
TARGETS = [
    Path.home() / ".codex" / "skills" / "manhua" / "session-distill" / "bin",
    Path.home() / ".grok" / "skills" / "session-distill" / "bin",
    Path.home() / "AppData" / "Local" / "hermes" / "skills" / "session-distill" / "bin",
    Path.home() / ".gemini" / "antigravity-cli" / "skills" / "session-distill" / "bin",
]

TRACKED = [
    "deep_distill_lib.py",
    "deep_distill_runner.py",
    "distill_core/revision.py",
    "distill_core/ingest.py",
    "distill_core/deep_run.py",
    "distill_core/adapter_common.py",
]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LibParityTests(unittest.TestCase):
    def test_shared_files_match_canonical(self):
        missing_targets = [target for target in TARGETS if not target.exists()]
        if missing_targets:
            self.skipTest(f"install targets missing: {', '.join(str(p) for p in missing_targets)}")

        canonical = {rel: file_hash(CANONICAL_BIN / rel) for rel in TRACKED}
        for target in TARGETS:
            for rel, expected in canonical.items():
                with self.subTest(target=str(target), rel=rel):
                    path = target / rel
                    self.assertTrue(path.exists(), f"missing {path}")
                    self.assertEqual(file_hash(path), expected)


if __name__ == "__main__":
    if str(CANONICAL_BIN) not in sys.path:
        sys.path.insert(0, str(CANONICAL_BIN))
    unittest.main()
