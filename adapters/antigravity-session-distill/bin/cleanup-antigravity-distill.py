#!/usr/bin/env python3
"""Cleanup helper for Antigravity session-distill workspace."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.request
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


def resolve_app_storage_path() -> Path | None:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            p = Path(appdata) / "Antigravity" / "app_storage.json"
            if p.exists():
                return p
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "Antigravity" / "app_storage.json"
        if p.exists():
            return p
    else:
        p = Path.home() / ".config" / "Antigravity" / "app_storage.json"
        if p.exists():
            return p
    return None


def discover_running_language_server() -> dict[str, Any] | None:
    """Discover running language_server.exe process, CSRF token, and HTTPS port."""
    if sys.platform != "win32":
        return None

    try:
        ps_cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name = 'language_server.exe'\" | Select-Object -Property ProcessId, CommandLine | ConvertTo-Json",
        ]
        proc_out = subprocess.check_output(ps_cmd, timeout=5).decode("utf-8").strip()
        if not proc_out:
            return None
        proc_data = json.loads(proc_out)
        if isinstance(proc_data, list):
            proc_data = proc_data[0]

        pid = proc_data.get("ProcessId")
        cmdline = proc_data.get("CommandLine", "")
        if not pid or not cmdline:
            return None

        token_m = re.search(r"--csrf_token\s+([a-zA-Z0-9-]+)", cmdline)
        csrf_token = token_m.group(1) if token_m else None
        if not csrf_token:
            return None

        ps_ports = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-NetTCPConnection -OwningProcess {pid} -State Listen | Select-Object -ExpandProperty LocalPort) -join ','",
        ]
        ports_str = subprocess.check_output(ps_ports, timeout=5).decode("utf-8").strip()
        candidate_ports = [int(p) for p in ports_str.split(",") if p.strip().isdigit()]

        ctx = ssl._create_unverified_context()
        https_port = None
        for p in candidate_ports:
            try:
                req = urllib.request.Request(
                    f"https://127.0.0.1:{p}/",
                    headers={"X-Codeium-Csrf-Token": csrf_token},
                )
                with urllib.request.urlopen(req, context=ctx, timeout=1) as resp:
                    if resp.status == 200:
                        https_port = p
                        break
            except Exception:
                pass

        if https_port:
            return {
                "pid": pid,
                "csrf_token": csrf_token,
                "https_port": https_port,
            }
    except Exception:
        pass
    return None


def rpc_delete_cascade_trajectories(
    purge_targets: list[str],
    ls_info: dict[str, Any],
) -> tuple[int, int]:
    """Call DeleteCascadeTrajectory via language server ConnectRPC HTTPS endpoint."""
    https_port = ls_info["https_port"]
    csrf_token = ls_info["csrf_token"]
    delete_url = f"https://127.0.0.1:{https_port}/exa.language_server_pb.LanguageServerService/DeleteCascadeTrajectory"
    headers = {
        "Content-Type": "application/json",
        "X-Codeium-Csrf-Token": csrf_token,
    }
    ctx = ssl._create_unverified_context()

    success = 0
    failed = 0
    for sid in purge_targets:
        body = json.dumps({"cascade_id": sid}).encode("utf-8")
        req = urllib.request.Request(delete_url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=3) as r:
                if r.status == 200:
                    success += 1
                else:
                    failed += 1
        except Exception:
            failed += 1
    return success, failed


def clean_app_storage(purge_targets: list[str], dry_run: bool = False) -> int:
    """Purge orphaned conversation panes, layouts, and comments from Electron app_storage.json."""
    storage_path = resolve_app_storage_path()
    if not storage_path or not storage_path.exists():
        return 0

    purge_set = set(purge_targets)
    try:
        with open(storage_path, "r", encoding="utf-8") as f:
            storage = json.load(f)
    except Exception as err:
        print(f"  Warning: failed to read {storage_path}: {err}")
        return 0

    removed = 0
    keys_to_delete = [
        k for k in storage.keys()
        if any(sid in k for sid in purge_set)
    ]
    if not dry_run:
        for k in keys_to_delete:
            del storage[k]
    removed += len(keys_to_delete)

    # Clean conversationPanes inside aux-pane-session / aux-pane-v2-session
    for aux_key in ["aux-pane-session", "aux-pane-v2-session"]:
        if aux_key in storage:
            val = storage[aux_key]
            if isinstance(val, str):
                try:
                    obj = json.loads(val)
                    changed = False
                    if "conversationPanes" in obj and isinstance(obj["conversationPanes"], dict):
                        cpanes = obj["conversationPanes"]
                        for sid in purge_set:
                            if sid in cpanes:
                                if not dry_run:
                                    del cpanes[sid]
                                removed += 1
                                changed = True
                    if changed and not dry_run:
                        storage[aux_key] = json.dumps(obj)
                except Exception:
                    pass

    # Clean artifact comments
    if "comments" in storage:
        comm = storage["comments"]
        if isinstance(comm, str):
            try:
                comm_obj = json.loads(comm)
                changed = False
                if "artifacts" in comm_obj and isinstance(comm_obj["artifacts"], dict):
                    to_del = [
                        k for k in comm_obj["artifacts"].keys()
                        if any(sid in k for sid in purge_set)
                    ]
                    for k in to_del:
                        if not dry_run:
                            del comm_obj["artifacts"][k]
                        removed += 1
                        changed = True
                if changed and not dry_run:
                    storage["comments"] = json.dumps(comm_obj)
            except Exception:
                pass

    if not dry_run and removed > 0:
        try:
            with open(storage_path, "w", encoding="utf-8") as f:
                json.dump(storage, f, indent=2)
        except Exception as err:
            print(f"  Warning: failed to write {storage_path}: {err}")

    return removed


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
    # Always protect current active session if available in environment
    for env_var in ["ANTIGRAVITY_CONVERSATION_ID", "CONVERSATION_ID"]:
        val = os.environ.get(env_var)
        if val:
            keep_set.add(val)

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
        purge_targets = [sid for sid in sorted(distilled_ids) if sid not in keep_set]
        print(f"==> Purging raw session data and UI records for {len(purge_targets)} distilled sessions...")
        homes = resolve_candidate_homes()

        # Step A: Notify running language server via native ConnectRPC
        if not dry_run and purge_targets:
            ls_info = discover_running_language_server()
            if ls_info:
                print(f"  Connected to running language server (PID={ls_info['pid']}, Port={ls_info['https_port']})")
                s_count, f_count = rpc_delete_cascade_trajectories(purge_targets, ls_info)
                print(f"  Language server RPC DeleteCascadeTrajectory: {s_count} succeeded, {f_count} failed")
            else:
                print("  Note: language server daemon not active; proceeding with direct storage cleanup")

        # Step B: Clean Electron UI app storage
        app_storage_cleaned = clean_app_storage(purge_targets, dry_run=dry_run)
        if app_storage_cleaned > 0:
            removed_count += app_storage_cleaned
            print(f"  Cleaned {app_storage_cleaned} UI storage entries from app_storage.json")

        # Step C: Clean raw disk files (brain folders, conv db, annotations)
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

        # Step D: Clean SQLite database and truncate WAL
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
                        cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                        conn.commit()
                        conn.close()
                    except Exception as err:
                        print(f"  Warning: failed to clean DB {db_path}: {err}")

        # Step E: Clean Protobuf index
        if not dry_run and purge_targets:
            purge_set = set(purge_targets)
            for home in homes:
                pb_path = home / "agyhub_summaries_proto.pb"
                if pb_path.exists():
                    try:
                        pb_bytes = pb_path.read_bytes()

                        def read_varint(data: bytes, pos: int) -> tuple[int, int]:
                            res = 0
                            shift = 0
                            while True:
                                b = data[pos]
                                pos += 1
                                res |= (b & 0x7F) << shift
                                if not (b & 0x80):
                                    return res, pos
                                shift += 7

                        def encode_varint(val: int) -> bytes:
                            res = bytearray()
                            while val >= 0x80:
                                res.append((val & 0x7F) | 0x80)
                                val >>= 7
                            res.append(val & 0x7F)
                            return bytes(res)

                        pos = 0
                        new_pb = bytearray()
                        while pos < len(pb_bytes):
                            tag, pos = read_varint(pb_bytes, pos)
                            ln, pos = read_varint(pb_bytes, pos)
                            payload = pb_bytes[pos:pos + ln]
                            pos += ln
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
