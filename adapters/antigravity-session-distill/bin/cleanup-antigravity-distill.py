#!/usr/bin/env python3
"""Cleanup helper for Antigravity session-distill workspace."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


def resolve_distill_dir() -> Path:
    if os.environ.get("AGY_DISTILL_DIR"):
        return Path(os.environ["AGY_DISTILL_DIR"])
    if os.environ.get("ANTIGRAVITY_CLI_ROOT"):
        base = Path(os.environ["ANTIGRAVITY_CLI_ROOT"])
    elif os.environ.get("AGY_HOME"):
        base = Path(os.environ["AGY_HOME"])
    else:
        base = Path.home() / ".gemini" / "antigravity-cli"
    return base / "session-distill"


def resolve_candidate_homes() -> list[Path]:
    homes: list[Path] = []
    if os.environ.get("AGY_HOME"):
        homes.append(Path(os.environ["AGY_HOME"]))
    if os.environ.get("ANTIGRAVITY_CLI_ROOT"):
        homes.append(Path(os.environ["ANTIGRAVITY_CLI_ROOT"]))
    home = Path.home()
    homes.append(home / ".gemini" / "antigravity-cli")
    homes.append(home / ".gemini" / "antigravity")

    valid: list[Path] = []
    seen: set[Path] = set()
    for h in homes:
        try:
            resolved = h.resolve()
            if resolved not in seen and h.exists():
                seen.add(resolved)
                valid.append(h)
        except Exception:
            pass
    return valid


def load_manifest(distill_dir: Path) -> dict[str, Any]:
    index_file = distill_dir / "session-index.json"
    if index_file.exists():
        try:
            return json.loads(index_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    manifest_file = distill_dir / "manifest.json"
    if manifest_file.exists():
        try:
            return json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"sessions": {}}


def get_distilled_session_ids(distill_dir: Path) -> set[str]:
    data = load_manifest(distill_dir)
    sessions = data.get("sessions", {})
    distilled = set()
    if isinstance(sessions, dict):
        for sid, meta in sessions.items():
            if meta.get("status") == "distilled":
                distilled.add(sid)
    elif isinstance(sessions, list):
        for item in sessions:
            if item.get("status") == "distilled":
                distilled.add(item.get("session_id"))
    return {s for s in distilled if s}


def cleanup_distill_workspace(
    target_type: str = "all",
    *,
    distill_dir: Path | None = None,
    keep_session_ids: list[str] | None = None,
    dry_run: bool = False,
    purge_distilled_raw: bool = False,
) -> int:
    distill_dir = distill_dir or resolve_distill_dir()
    if not distill_dir.exists():
        print(f"Distill directory does not exist: {distill_dir}")
        return 0

    keep_set = set(keep_session_ids or [])
    distilled_ids = get_distilled_session_ids(distill_dir)

    packets_dir = distill_dir / "packets"
    removed_count = 0

    if target_type in ("all", "packets") and packets_dir.exists():
        for packet_file in packets_dir.glob("*.md"):
            sid = packet_file.stem
            if sid in keep_set:
                continue
            if dry_run:
                print(f"  [dry-run] Would remove packet: {packet_file.name}")
            else:
                try:
                    packet_file.unlink()
                    removed_count += 1
                    print(f"  Removed packet: {packet_file.name}")
                except OSError as err:
                    print(f"  Failed to remove {packet_file.name}: {err}")

    workdirs_dir = distill_dir / "distilled" / "workdirs"
    if target_type in ("all", "workdirs") and workdirs_dir.exists():
        for item in workdirs_dir.iterdir():
            sid = item.name
            if sid in keep_set:
                continue
            if dry_run:
                print(f"  [dry-run] Would remove workdir: {item.name}")
            else:
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                    removed_count += 1
                    print(f"  Removed workdir: {item.name}")
                except OSError as err:
                    print(f"  Failed to remove {item.name}: {err}")

    if purge_distilled_raw and distilled_ids:
        print(f"==> Purging raw session data and UI records for {len(distilled_ids)} distilled sessions...")
        homes = resolve_candidate_homes()
        purge_targets = [sid for sid in distilled_ids if sid not in keep_set]

        # 1. Clean disk files (brain, conversations, annotations)
        for sid in purge_targets:
            for home in homes:
                brain_folder = home / "brain" / sid
                if brain_folder.exists() and brain_folder.is_dir():
                    if dry_run:
                        print(f"  [dry-run] Would purge brain: {brain_folder}")
                    else:
                        shutil.rmtree(brain_folder, ignore_errors=True)
                        removed_count += 1
                conv_db = home / "conversations" / f"{sid}.db"
                if conv_db.exists():
                    if dry_run:
                        print(f"  [dry-run] Would remove conv db: {conv_db}")
                    else:
                        conv_db.unlink(missing_ok=True)
                        removed_count += 1
                anno_file = home / "annotations" / f"{sid}.pbtxt"
                if anno_file.exists():
                    if dry_run:
                        print(f"  [dry-run] Would remove annotation: {anno_file}")
                    else:
                        anno_file.unlink(missing_ok=True)
                        removed_count += 1

        # 2. Clean SQLite database (conversation_summaries.db)
        if not dry_run and purge_targets:
            import sqlite3
            for home in homes:
                db_path = home / "conversation_summaries.db"
                if db_path.exists():
                    try:
                        conn = sqlite3.connect(str(db_path))
                        cur = conn.cursor()
                        placeholders = ",".join("?" for _ in purge_targets)
                        cur.execute(f"DELETE FROM conversation_summaries WHERE conversation_id IN ({placeholders})", purge_targets)
                        try:
                            cur.execute(f"DELETE FROM conversations_fts WHERE conversation_id IN ({placeholders})", purge_targets)
                        except Exception:
                            pass
                        conn.commit()
                        conn.close()
                    except Exception as err:
                        print(f"  Warning: failed to clean DB {db_path}: {err}")

        # 3. Clean Protobuf index (agyhub_summaries_proto.pb)
        if not dry_run and purge_targets:
            purge_set = set(purge_targets)
            for home in homes:
                pb_path = home / "agyhub_summaries_proto.pb"
                if pb_path.exists():
                    try:
                        pb_bytes = pb_path.read_bytes()
                        def read_varint(data, pos):
                            res = 0; shift = 0
                            while True:
                                b = data[pos]; pos += 1
                                res |= (b & 0x7f) << shift
                                if not (b & 0x80): return res, pos
                                shift += 7
                        def encode_varint(val):
                            res = bytearray()
                            while val >= 0x80:
                                res.append((val & 0x7f) | 0x80); val >>= 7
                            res.append(val & 0x7f)
                            return bytes(res)
                        pos = 0; new_pb = bytearray()
                        while pos < len(pb_bytes):
                            tag, pos = read_varint(pb_bytes, pos)
                            ln, pos = read_varint(pb_bytes, pos)
                            payload = pb_bytes[pos:pos+ln]; pos += ln
                            cid = ""
                            if payload.startswith(b"\n$"):
                                cid = payload[2:38].decode("ascii", errors="ignore")
                            if not cid or cid not in purge_set:
                                new_pb.extend(encode_varint(tag))
                                new_pb.extend(encode_varint(len(payload)))
                                new_pb.extend(payload)
                        pb_path.write_bytes(bytes(new_pb))
                    except Exception as err:
                        print(f"  Warning: failed to clean protobuf {pb_path}: {err}")

    print(f"==> Cleanup completed. Total items removed: {removed_count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup Antigravity session-distill workspace artifacts")
    parser.add_argument("target", nargs="?", default="all", choices=["all", "packets", "workdirs"])
    parser.add_argument("--keep", nargs="*", default=[], help="Session IDs to preserve")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without deleting")
    parser.add_argument("--purge-distilled-raw", action="store_true", help="Purge raw brain folders of distilled sessions")
    args = parser.parse_args()

    return cleanup_distill_workspace(
        target_type=args.target,
        keep_session_ids=args.keep,
        dry_run=args.dry_run,
        purge_distilled_raw=args.purge_distilled_raw,
    )


if __name__ == "__main__":
    raise SystemExit(main())
