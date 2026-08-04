#!/usr/bin/env python3
"""Check every repository copy of ``distill_core`` for content drift."""

from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_CORE = REPO_ROOT / "shared" / "distill_core"
PLATFORM_BINS = [
    REPO_ROOT / "adapters" / "cursor-session-distill" / "bin",
    REPO_ROOT / "adapters" / "codex-session-distill" / "bin",
    REPO_ROOT / "adapters" / "grok-session-distill" / "bin",
    REPO_ROOT / "adapters" / "claude-session-distill" / "bin",
    REPO_ROOT / "adapters" / "hermes-session-distill" / "bin",
    REPO_ROOT / "adapters" / "antigravity-session-distill" / "bin",
    REPO_ROOT / "adapters" / "opencode-session-distill" / "bin",
    REPO_ROOT / "helpers" / "packet-memory-export" / "bin",
]


def tracked_files(root: Path) -> dict[Path, str]:
    files: dict[Path, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        files[path.relative_to(root)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def assert_matches(test: unittest.TestCase, expected: dict[Path, str], root: Path) -> None:
    test.assertTrue(root.is_dir(), f"missing distill_core: {root}")
    actual = tracked_files(root)
    test.assertEqual(set(expected), set(actual), f"file set drift in {root}")
    for relative_path, expected_hash in expected.items():
        test.assertEqual(expected_hash, actual[relative_path], f"content drift in {root / relative_path}")


class LibParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.expected = tracked_files(SOURCE_CORE)
        self.assertTrue(self.expected, f"missing shared core: {SOURCE_CORE}")

    def test_repo_copies_match_shared_core(self):
        for target_bin in PLATFORM_BINS:
            with self.subTest(target=target_bin):
                assert_matches(self, self.expected, target_bin / "distill_core")

    def test_configured_install_copies_match_shared_core(self):
        """Installed copies are opt-in so the repository test stays portable.

        Set ``SESSION_DISTILL_PARITY_INSTALL_ROOTS`` to path-separated bin
        directories on a machine that manages installed skill copies.  A
        configured missing or stale installation is always a test failure.
        """

        configured = [Path(value) for value in os.environ.get("SESSION_DISTILL_PARITY_INSTALL_ROOTS", "").split(os.pathsep) if value]
        for install_bin in configured:
            with self.subTest(target=install_bin):
                assert_matches(self, self.expected, install_bin / "distill_core")


if __name__ == "__main__":
    unittest.main()
