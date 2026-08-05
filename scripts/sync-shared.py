#!/usr/bin/env python3
"""Single consolidated script to sync and check shared libraries across all adapter binaries."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = REPO_ROOT / "shared"

SOURCE_CORE = SHARED_DIR / "distill_core"
SOURCE_LIB = SHARED_DIR / "deep_distill_lib.py"
SOURCE_RUNNER = SHARED_DIR / "deep_distill_runner.py"
SOURCE_WORKFLOW = SHARED_DIR / "references" / "deep-distill-workflow.md"

PLATFORM_ADAPTER_BINS = [
    REPO_ROOT / "adapters" / "claude-session-distill" / "bin",
    REPO_ROOT / "adapters" / "codex-session-distill" / "bin",
    REPO_ROOT / "adapters" / "cursor-session-distill" / "bin",
    REPO_ROOT / "adapters" / "grok-session-distill" / "bin",
    REPO_ROOT / "adapters" / "hermes-session-distill" / "bin",
    REPO_ROOT / "adapters" / "antigravity-session-distill" / "bin",
    REPO_ROOT / "adapters" / "opencode-session-distill" / "bin",
]

CORE_TARGET_BINS = PLATFORM_ADAPTER_BINS + [
    REPO_ROOT / "helpers" / "packet-memory-export" / "bin",
]


def _tracked_files(root: Path) -> dict[Path, str]:
    files: dict[Path, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        files[path.relative_to(root)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def check_sync() -> int:
    failures = 0

    # 1. Check distill_core directory drift
    if not SOURCE_CORE.is_dir():
        print(f"missing source core: {SOURCE_CORE}")
        return 1
    expected_core = _tracked_files(SOURCE_CORE)
    for target_bin in CORE_TARGET_BINS:
        destination = target_bin / "distill_core"
        if not destination.is_dir():
            print(f"missing vendored core: {destination.relative_to(REPO_ROOT)}")
            failures += 1
            continue
        actual = _tracked_files(destination)
        if set(expected_core) != set(actual) or any(expected_core[p] != actual[p] for p in expected_core):
            print(f"distill_core drift: {destination.relative_to(REPO_ROOT)}")
            failures += 1

    # 2. Check deep_distill_lib.py drift
    lib_hash = hashlib.sha256(SOURCE_LIB.read_bytes()).hexdigest()
    for target_bin in PLATFORM_ADAPTER_BINS:
        target_lib = target_bin / "deep_distill_lib.py"
        if not target_lib.exists() or hashlib.sha256(target_lib.read_bytes()).hexdigest() != lib_hash:
            print(f"deep_distill_lib drift: {target_lib.relative_to(REPO_ROOT)}")
            failures += 1

    # 3. Check deep_distill_runner.py drift
    runner_hash = hashlib.sha256(SOURCE_RUNNER.read_bytes()).hexdigest()
    for target_bin in PLATFORM_ADAPTER_BINS:
        target_runner = target_bin / "deep_distill_runner.py"
        if not target_runner.exists() or hashlib.sha256(target_runner.read_bytes()).hexdigest() != runner_hash:
            print(f"deep_distill_runner drift: {target_runner.relative_to(REPO_ROOT)}")
            failures += 1

    # 4. Check deep-distill-workflow.md drift
    workflow_hash = hashlib.sha256(SOURCE_WORKFLOW.read_bytes()).hexdigest()
    for target_bin in PLATFORM_ADAPTER_BINS:
        target_workflow = target_bin.parent / "references" / "deep-distill-workflow.md"
        if not target_workflow.exists() or hashlib.sha256(target_workflow.read_bytes()).hexdigest() != workflow_hash:
            print(f"workflow reference drift: {target_workflow.relative_to(REPO_ROOT)}")
            failures += 1

    if failures:
        print(f"==> Shared library sync check FAILED ({failures} drift(s) found)")
        return 1
    print("==> Shared library sync check OK")
    return 0


def sync_all() -> int:
    for target_bin in CORE_TARGET_BINS:
        destination = target_bin / "distill_core"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(SOURCE_CORE, destination)
        print(f"synced distill_core -> {destination.relative_to(REPO_ROOT)}")

    for target_bin in PLATFORM_ADAPTER_BINS:
        shutil.copy2(SOURCE_LIB, target_bin / "deep_distill_lib.py")
        shutil.copy2(SOURCE_RUNNER, target_bin / "deep_distill_runner.py")
        ref_dir = target_bin.parent / "references"
        ref_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_WORKFLOW, ref_dir / "deep-distill-workflow.md")
        print(f"synced shared files -> {target_bin.parent.relative_to(REPO_ROOT)}")

    return check_sync()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail on code drift without modifying files")
    args = parser.parse_args(argv)
    return check_sync() if args.check else sync_all()


if __name__ == "__main__":
    raise SystemExit(main())
