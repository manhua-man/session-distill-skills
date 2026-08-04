#!/usr/bin/env python3
"""Shared Deep Distill batch runner with chunk checkpoint resume."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_BIN_DIR = Path(__file__).resolve().parent
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

import deep_distill_lib as ddl
from distill_core.deep_run import extract_session_claims


def load_adapter(adapter_script: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, adapter_script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_deep_batch(
    *,
    mod: Any,
    platform: str,
    batch: list[dict[str, Any]],
    answer_dir: Path,
    check_work_dir: Path,
    packet_prefix: str,
    project_path_key: str,
    offset: int,
    force_bundle: bool,
    force_extract: bool,
    queue_file: Path | None = None,
    queue_writer: Callable[..., None] | None = None,
) -> int:
    mod.ensure_dirs()
    answer_dir.mkdir(parents=True, exist_ok=True)
    check_work_dir.mkdir(parents=True, exist_ok=True)

    ids = [session["session_id"] for session in batch]
    print(f"==> {platform} deep distill batch: {len(batch)} sessions (offset={offset})")
    for session in batch:
        label = (session.get("thread_name") or session.get("name") or "")[:60]
        print(f"  - {session['session_id']} {label}")

    if force_bundle:
        mod.cmd_bundle(next_count=0, force=True, session_ids=ids)

    for meta in batch:
        sid = meta["session_id"]
        path = mod.PACKETS_DIR / f"{packet_prefix}{sid}.md"
        if not path.exists():
            print(f"missing packet: {path}")
            continue
        packet_text = path.read_text(encoding="utf-8", errors="replace")
        claims, stats = extract_session_claims(
            session_meta=meta,
            packet_text=packet_text,
            claim_extractor=ddl.extract_claims_from_turns,
            packet_claim_extractor=ddl.extract_claims,
            force=force_extract,
        )
        extract_meta = {
            **meta,
            "extract_mode": stats.get("mode", ""),
            "current_revision_id": stats.get("revision_id") or meta.get("current_revision_id", ""),
        }
        questions = ddl.default_questions(claims)
        out = answer_dir / f"{sid}.md"
        out.write_text(
            ddl.render_answer_packet(
                sid,
                extract_meta,
                claims,
                questions,
                platform=platform,
                project_path=str(meta.get(project_path_key) or ""),
            ),
            encoding="utf-8",
        )
        if stats.get("mode") == "chunked":
            print(
                f"  -> claims={len(claims)} chunks resumed={stats.get('chunks_resumed', 0)} "
                f"processed={stats.get('chunks_processed', 0)} answer-packet={out}"
            )
        else:
            print(f"  -> claims={len(claims)} mode={stats.get('mode')} answer-packet={out}")

    batch_label = f"{platform} batch offset {offset} ({len(batch)} sessions)"
    report = ddl.render_check_work_report(
        batch_label=batch_label,
        session_ids=ids,
        promoted=[],
        not_promoted=[],
        verdict="PENDING",
    )
    report_path = check_work_dir / f"batch-offset-{offset}-report.md"
    report_path.write_text(report, encoding="utf-8")
    if queue_writer:
        queue_writer(batch=batch, offset=offset)
    elif queue_file:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        queue_file.write_text(
            f"# Servers Deep Distillation Queue ({platform})\n\nUpdated: {stamp}\n\n"
            f"Batch offset `{offset}` | sessions: {len(batch)}\n",
            encoding="utf-8",
        )

    print(f"==> check-work stub: {report_path}")
    print("==> Next: answer-me verify each Q → promote ANSWERED only → update check-work → mark distilled")
    if queue_file:
        print(f"==> Queue file: {queue_file}")
    return 0


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--force-bundle", action="store_true", default=True)
    parser.add_argument("--force-extract", action="store_true", default=False)
    parser.add_argument("--session-ids", nargs="*", default=[])
    parser.add_argument("--project", type=str, default="servers")
    parser.add_argument("--reindex", action="store_true", default=False)
    parser.add_argument("--include-processed", action="store_true", default=False)
    return parser
