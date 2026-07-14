#!/usr/bin/env python3
"""Publish shared session-distill core from canonical Cursor install to all platforms."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

CANONICAL_BIN = Path(__file__).resolve().parent
SHARED_ITEMS = (
    "distill_core",
    "deep_distill_lib.py",
    "deep_distill_runner.py",
)

INSTALL_TARGETS = [
    Path.home() / ".codex" / "skills" / "manhua" / "session-distill" / "bin",
    Path.home() / ".grok" / "skills" / "session-distill" / "bin",
    Path.home() / ".claude" / "skills" / "manhua" / "codex-session-distill" / "bin",
    Path.home() / ".claude" / "skills" / "manhua" / "session-distill" / "bin",
    Path.home() / "AppData" / "Local" / "hermes" / "skills" / "session-distill" / "bin",
    Path.home() / ".gemini" / "antigravity-cli" / "skills" / "session-distill" / "bin",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_canonical_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in ("deep_distill_lib.py", "deep_distill_runner.py"):
        path = CANONICAL_BIN / name
        if path.exists():
            hashes[name] = sha256_file(path)
    core_dir = CANONICAL_BIN / "distill_core"
    if core_dir.exists():
        for path in sorted(core_dir.rglob("*")):
            if path.is_file() and path.suffix != ".pyc":
                rel = path.relative_to(CANONICAL_BIN).as_posix()
                hashes[rel] = sha256_file(path)
    return hashes


def copy_shared_item(name: str, target_bin: Path) -> None:
    source = CANONICAL_BIN / name
    destination = target_bin / name
    if not source.exists():
        raise FileNotFoundError(source)
    target_bin.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def sync_all(*, dry_run: bool = False) -> int:
    print(f"==> Canonical: {CANONICAL_BIN}")
    canonical_hashes = collect_canonical_hashes()

    mismatches = 0
    for target in INSTALL_TARGETS:
        print(f"\n-> {target}")
        if not target.parent.exists():
            print("   skip (parent missing)")
            continue
        if dry_run:
            print("   dry-run only")
            continue
        for item in SHARED_ITEMS:
            copy_shared_item(item, target)
            print(f"   copied {item}")
        for rel, expected in canonical_hashes.items():
            path = target / rel
            if not path.exists():
                print(f"   MISSING {rel}")
                mismatches += 1
                continue
            actual = sha256_file(path)
            if actual != expected:
                print(f"   MISMATCH {rel}")
                mismatches += 1
    if mismatches:
        print(f"\n==> Sync completed with {mismatches} mismatch(es)")
        return 1
    print("\n==> Sync OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync shared session-distill core to all platform installs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return sync_all(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
