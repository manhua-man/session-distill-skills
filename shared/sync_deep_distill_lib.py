#!/usr/bin/env python3
"""Copy shared/deep_distill_lib.py into every platform bin/ directory."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "deep_distill_lib.py"
TARGETS = [
    ROOT.parent / "session-distill" / "bin" / "deep_distill_lib.py",
    ROOT.parent / "codex-session-distill" / "bin" / "deep_distill_lib.py",
    ROOT.parent / "cursor-session-distill" / "bin" / "deep_distill_lib.py",
    ROOT.parent / "grok-session-distill" / "bin" / "deep_distill_lib.py",
    ROOT.parent / "hermes-session-distill" / "bin" / "deep_distill_lib.py",
    ROOT.parent / "antigravity-session-distill" / "bin" / "deep_distill_lib.py",
    ROOT.parent / "opencode-session-distill" / "bin" / "deep_distill_lib.py",
]
WORKFLOW_SOURCE = ROOT / "references" / "deep-distill-workflow.md"
WORKFLOW_TARGETS = [
    ROOT.parent / "session-distill" / "references" / "deep-distill-workflow.md",
    ROOT.parent / "codex-session-distill" / "references" / "deep-distill-workflow.md",
    ROOT.parent / "cursor-session-distill" / "references" / "deep-distill-workflow.md",
    ROOT.parent / "grok-session-distill" / "references" / "deep-distill-workflow.md",
    ROOT.parent / "hermes-session-distill" / "references" / "deep-distill-workflow.md",
    ROOT.parent / "antigravity-session-distill" / "references" / "deep-distill-workflow.md",
    ROOT.parent / "opencode-session-distill" / "references" / "deep-distill-workflow.md",
]


def main() -> int:
    if not SOURCE.exists():
        print(f"missing source: {SOURCE}")
        return 1
    for target in TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE, target)
        print(f"synced lib -> {target}")
    if WORKFLOW_SOURCE.exists():
        for target in WORKFLOW_TARGETS:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(WORKFLOW_SOURCE, target)
            print(f"synced workflow -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
