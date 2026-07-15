#!/usr/bin/env python3
"""Copy shared/distill_core into every platform bin/ directory in this repo."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_CORE = REPO_ROOT / "shared" / "distill_core"

PLATFORM_BINS = [
    REPO_ROOT / "cursor-session-distill" / "bin",
    REPO_ROOT / "codex-session-distill" / "bin",
    REPO_ROOT / "grok-session-distill" / "bin",
    REPO_ROOT / "session-distill" / "bin",
    REPO_ROOT / "hermes-session-distill" / "bin",
    REPO_ROOT / "antigravity-session-distill" / "bin",
    REPO_ROOT / "opencode-session-distill" / "bin",
    REPO_ROOT / "packet-memory-export" / "bin",
]


def sync_repo_core() -> int:
    if not SOURCE_CORE.exists():
        print(f"missing source core: {SOURCE_CORE}")
        return 1
    for target_bin in PLATFORM_BINS:
        destination = target_bin / "distill_core"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(SOURCE_CORE, destination)
        print(f"copied distill_core -> {destination}")
    print("==> Repo distill_core sync OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(sync_repo_core())
