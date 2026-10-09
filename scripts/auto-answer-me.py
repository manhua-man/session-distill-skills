#!/usr/bin/env python3
"""Auto-Answer-Me: Automated claim verification engine.

Verifies deterministic facts (FILE_EXISTS, SYMBOL_GREP, CONFIG_VALUE, ROUTE_ENDPOINT, MIGRATION)
against target codebase HEAD, tagging verified claims as ANSWERED with code anchors.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add shared to path
REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = REPO_ROOT / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from distill_core.auto_verify import AutoVerifier, CodebaseIndex, VerificationResult


def resolve_codebase(explicit_path: str | None) -> Path:
    if explicit_path:
        p = Path(explicit_path).resolve()
        if p.is_dir():
            return p
        raise FileNotFoundError(f"Codebase path does not exist: {p}")

    env_path = os.environ.get("TARGET_CODEBASE")
    if env_path:
        p = Path(env_path).resolve()
        if p.is_dir():
            return p

    cwd = Path.cwd().resolve()
    # Check if cwd is repo root
    if (cwd / "package.json").exists() or (cwd / ".git").exists():
        return cwd

    # Check parent if in subfolder
    for parent in [cwd.parent, cwd.parent.parent]:
        if (parent / "package.json").exists():
            return parent

    return cwd


def cmd_check_claim(args: argparse.Namespace) -> int:
    codebase = resolve_codebase(args.codebase)
    verifier = AutoVerifier(codebase)
    result = verifier.verify_claim(args.claim)

    if args.json:
        data = {
            "status": result.status,
            "lens": result.lens,
            "rule_type": result.rule_type,
            "answer": result.answer,
            "evidence": result.evidence,
            "confidence": result.confidence,
            "codebase": str(codebase),
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    print("--- Auto-Answer-Me Claim Verification ---")
    print(f"Codebase:   {codebase}")
    print(f"Claim:      {args.claim}")
    print(f"Status:     {result.status}")
    print(f"Rule Type:  {result.rule_type}")
    print(f"Lens:       {result.lens}")
    print(f"Confidence: {result.confidence:.2f}")
    if result.evidence:
        print(f"Evidence:   {result.evidence}")
    if result.answer:
        print(f"Answer:     {result.answer}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    packet_path = Path(args.packet).resolve()
    if not packet_path.is_file():
        print(f"Error: Answer packet file not found: {packet_path}", file=sys.stderr)
        return 1

    codebase = resolve_codebase(args.codebase)
    verifier = AutoVerifier(codebase)
    res = verifier.verify_answer_packet(packet_path, apply=args.apply)

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    print(f"Packet:         {packet_path.name}")
    print(f"Codebase:       {codebase}")
    print(f"Total Claims:   {res['total_questions']}")
    print(f"Auto-Verified:  {res['auto_verified']}")
    print(f"Applied Update: {res['applied']}")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    codebase = resolve_codebase(args.codebase)
    verifier = AutoVerifier(codebase)

    target_dirs: list[Path] = []
    if args.dir:
        d = Path(args.dir).resolve()
        if d.is_dir():
            target_dirs.append(d)
        else:
            print(f"Error: Directory not found: {d}", file=sys.stderr)
            return 1
    else:
        # Default search across common platform packet paths
        home = Path.home()
        for plat in ["cursor", "grok", "claude", "codex", "hermes", "antigravity", "opencode"]:
            cand = home / f".{plat}" / "session-distill" / "distilled" / "answer-packets"
            if cand.is_dir():
                target_dirs.append(cand)

    total_packets = 0
    total_verified = 0

    for d in target_dirs:
        for packet_file in d.glob("*.md"):
            total_packets += 1
            res = verifier.verify_answer_packet(packet_file, apply=args.apply)
            if res["auto_verified"] > 0:
                total_verified += res["auto_verified"]
                print(f"[{packet_file.name}] Verified {res['auto_verified']}/{res['total_questions']} claims (applied={args.apply})")

    print(f"Batch completed: {total_packets} packets scanned, {total_verified} claims verified.")
    return 0


def cmd_self_test(args: argparse.Namespace) -> int:
    print("Running AutoVerifier self-test...")
    ok = AutoVerifier.self_test()
    if ok:
        print("AutoVerifier self-test PASSED")
        return 0
    print("AutoVerifier self-test FAILED", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", help="sub-command help")

    # check-claim
    p_claim = subparsers.add_parser("check-claim", help="Verify a single claim string")
    p_claim.add_argument("claim", type=str, help="Claim statement to verify")
    p_claim.add_argument("--codebase", type=str, default="", help="Path to codebase HEAD")
    p_claim.add_argument("--json", action="store_true", help="Output JSON")

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify an answer packet markdown file")
    p_verify.add_argument("packet", type=str, help="Path to answer packet markdown")
    p_verify.add_argument("--codebase", type=str, default="", help="Path to codebase HEAD")
    p_verify.add_argument("--apply", action="store_true", help="Update answer packet file in place")
    p_verify.add_argument("--json", action="store_true", help="Output JSON")

    # batch
    p_batch = subparsers.add_parser("batch", help="Batch verify answer packets across directories")
    p_batch.add_argument("--dir", type=str, default="", help="Specific answer packets directory")
    p_batch.add_argument("--codebase", type=str, default="", help="Path to codebase HEAD")
    p_batch.add_argument("--apply", action="store_true", help="Update answer packet files in place")

    # self-test
    subparsers.add_parser("self-test", help="Run built-in verification engine self-test")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    if args.command == "check-claim":
        return cmd_check_claim(args)
    if args.command == "verify":
        return cmd_verify(args)
    if args.command == "batch":
        return cmd_batch(args)
    if args.command == "self-test":
        return cmd_self_test(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
