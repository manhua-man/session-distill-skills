#!/usr/bin/env python3
"""Synchronize, or verify, the vendored ``distill_core`` copies in this repo."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
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


def _tracked_files(root: Path) -> dict[Path, str]:
    files: dict[Path, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        files[path.relative_to(root)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def check_repo_core() -> int:
    if not SOURCE_CORE.is_dir():
        print(f"missing source core: {SOURCE_CORE}")
        return 1
    expected = _tracked_files(SOURCE_CORE)
    failures = 0
    for target_bin in PLATFORM_BINS:
        destination = target_bin / "distill_core"
        if not destination.is_dir():
            print(f"missing vendored core: {destination}")
            failures += 1
            continue
        actual = _tracked_files(destination)
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        changed = sorted(path for path in set(expected) & set(actual) if expected[path] != actual[path])
        if missing or unexpected or changed:
            failures += 1
            print(f"distill_core drift: {destination}")
            for label, paths in (("missing", missing), ("unexpected", unexpected), ("changed", changed)):
                for path in paths:
                    print(f"  {label}: {path}")
    if failures:
        print(f"==> Repo distill_core check FAILED ({failures} target(s))")
        return 1
    print("==> Repo distill_core check OK")
    return 0


def sync_repo_core() -> int:
    if not SOURCE_CORE.is_dir():
        print(f"missing source core: {SOURCE_CORE}")
        return 1
    for target_bin in PLATFORM_BINS:
        destination = target_bin / "distill_core"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(SOURCE_CORE, destination)
        print(f"copied distill_core -> {destination}")
    return check_repo_core()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail on copy drift without writing files")
    args = parser.parse_args(argv)
    return check_repo_core() if args.check else sync_repo_core()


if __name__ == "__main__":
    raise SystemExit(main())
