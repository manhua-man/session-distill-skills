#!/usr/bin/env python3
"""Run repo-local self-tests for all session-distill adapters."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SELF_TESTS = [
    REPO_ROOT / "adapters" / "cursor-session-distill" / "bin" / "cursor-session-distill.py",
    REPO_ROOT / "adapters" / "codex-session-distill" / "bin" / "session-distill.py",
    REPO_ROOT / "adapters" / "grok-session-distill" / "bin" / "grok-session-distill.py",
    REPO_ROOT / "adapters" / "claude-session-distill" / "bin" / "session-distill.py",
    REPO_ROOT / "adapters" / "hermes-session-distill" / "bin" / "hermes-session-distill.py",
    REPO_ROOT / "adapters" / "antigravity-session-distill" / "bin" / "antigravity-session-distill.py",
    REPO_ROOT / "adapters" / "opencode-session-distill" / "bin" / "opencode-session-distill.py",
    REPO_ROOT / "helpers" / "packet-memory-export" / "bin" / "packet-memory-export.py",
]

UNIT_TESTS = [
    REPO_ROOT / "adapters" / "cursor-session-distill" / "tests" / "test_distill_core.py",
    REPO_ROOT / "adapters" / "cursor-session-distill" / "tests" / "test_lib_parity.py",
    REPO_ROOT / "tests" / "contract" / "test_contracts.py",
]


def run(command: list[str]) -> int:
    print(f"\n==> {' '.join(command)}")
    completed = subprocess.run(command, cwd=REPO_ROOT)
    return completed.returncode


def check_hardcoded_paths() -> int:
    print("\n==> Checking for hardcoded local paths in Python files...")
    hardcoded_found = 0
    forbidden_forward = "E:/" + "project/servers"
    forbidden_back = "E:\\\\" + "project\\\\servers"
    for path in REPO_ROOT.rglob("*.py"):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if forbidden_forward in text or forbidden_back in text:
            print(f"FAILED: Hardcoded path found in {path.relative_to(REPO_ROOT)}")
            hardcoded_found += 1
    if hardcoded_found:
        return 1
    print("OK: No hardcoded local paths found.")
    return 0


def main() -> int:
    sync_script = REPO_ROOT / "scripts" / "sync-shared.py"
    code = run([sys.executable, str(sync_script), "--check"])
    if code != 0:
        return code

    if check_hardcoded_paths() != 0:
        return 1

    failures = 0
    for script in SELF_TESTS:
        if not script.exists():
            print(f"skip missing adapter: {script}")
            failures += 1
            continue
        code = run([sys.executable, str(script), "self-test"])
        if code != 0:
            print(f"FAILED self-test: {script.relative_to(REPO_ROOT)}")
            failures += 1

    # Verify deep-distill-run.py wrappers execute --help cleanly
    for runner in REPO_ROOT.rglob("deep-distill-run.py"):
        code = run([sys.executable, str(runner), "--help"])
        if code != 0:
            print(f"FAILED runner --help check: {runner.relative_to(REPO_ROOT)}")
            failures += 1

    for test_path in UNIT_TESTS:
        if not test_path.exists():
            print(f"skip missing test: {test_path}")
            failures += 1
            continue
        code = run([sys.executable, str(test_path)])
        if code != 0:
            print(f"FAILED unit-test: {test_path.relative_to(REPO_ROOT)}")
            failures += 1

    if failures:
        print(f"\n==> FAILED ({failures} suite(s))")
        return 1
    print("\n==> All repo tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
