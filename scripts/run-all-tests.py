#!/usr/bin/env python3
"""Run repo-local self-tests for all session-distill adapters."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SELF_TESTS = [
    REPO_ROOT / "cursor-session-distill" / "bin" / "cursor-session-distill.py",
    REPO_ROOT / "codex-session-distill" / "bin" / "session-distill.py",
    REPO_ROOT / "grok-session-distill" / "bin" / "grok-session-distill.py",
    REPO_ROOT / "session-distill" / "bin" / "session-distill.py",
    REPO_ROOT / "hermes-session-distill" / "bin" / "hermes-session-distill.py",
    REPO_ROOT / "antigravity-session-distill" / "bin" / "antigravity-session-distill.py",
    REPO_ROOT / "opencode-session-distill" / "bin" / "opencode-session-distill.py",
    REPO_ROOT / "packet-memory-export" / "bin" / "packet-memory-export.py",
]

UNIT_TESTS = [
    REPO_ROOT / "cursor-session-distill" / "tests" / "test_distill_core.py",
    REPO_ROOT / "tests" / "contract" / "test_contracts.py",
]


def run(command: list[str]) -> int:
    print(f"\n==> {' '.join(command)}")
    completed = subprocess.run(command, cwd=REPO_ROOT)
    return completed.returncode


def main() -> int:
    sync_script = REPO_ROOT / "scripts" / "sync-repo-distill-core.py"
    code = run([sys.executable, str(sync_script)])
    if code != 0:
        return code

    failures = 0
    for script in SELF_TESTS:
        if not script.exists():
            print(f"skip missing adapter: {script}")
            failures += 1
            continue
        code = run([sys.executable, str(script), "self-test"])
        if code != 0:
            failures += 1

    for test_path in UNIT_TESTS:
        if not test_path.exists():
            print(f"skip missing test: {test_path}")
            failures += 1
            continue
        code = run([sys.executable, str(test_path)])
        if code != 0:
            failures += 1

    if failures:
        print(f"\n==> FAILED ({failures} suite(s))")
        return 1
    print("\n==> All repo tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
