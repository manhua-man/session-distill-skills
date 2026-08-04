#!/usr/bin/env python3
"""Unit tests for distill_core (portable, no hardcoded user paths)."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from distill_core.candidate_id import make_candidate_id, normalize_claim
from distill_core.adapter_common import messages_to_turns
from distill_core.chunks import rebuild_transcript, split_turns_into_chunks
from distill_core.final_review import promotion_allowed, promotion_blocked_reasons, validate_final_review
from distill_core.ingest import ingest_revision, verify_revision_rebuild
from distill_core.queue import compute_queue_status_on_index, needs_redistill
from distill_core.revision import compute_revision_id, compute_source_fingerprint


def _sample_turns(extra_user: str = "") -> list[dict]:
    turns = [
        {
            "turn_id": "t1",
            "user_messages": ["hello" + extra_user],
            "assistant_updates": ["working"],
            "final_answers": ["done"],
        }
    ]
    return turns


class DistillCoreTests(unittest.TestCase):
    def test_revision_id_stable_when_fingerprint_changes(self):
        turns = _sample_turns()
        first_fp = {"size_bytes": 10, "mtime": "a"}
        second_fp = {"size_bytes": 99, "mtime": "b"}
        first = compute_revision_id("sid", "codex", turns, first_fp)
        second = compute_revision_id("sid", "codex", turns, second_fp)
        self.assertEqual(first, second)

    def test_revision_id_changes_when_content_changes(self):
        fp = {"size_bytes": 10}
        first = compute_revision_id("sid", "codex", _sample_turns(), fp)
        second = compute_revision_id("sid", "codex", _sample_turns("!"), fp)
        self.assertNotEqual(first, second)

    def test_source_fingerprint_stable_for_same_fields(self):
        a = compute_source_fingerprint({"size_bytes": 1, "mtime": "x"})
        b = compute_source_fingerprint({"mtime": "x", "size_bytes": 1})
        self.assertEqual(a, b)

    def test_lossless_ingest_rebuilds_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            distill_dir = Path(tmp)
            turns = _sample_turns("x" * 5000)
            turns.append(
                {
                    "turn_id": "t2",
                    "user_messages": ["second"],
                    "assistant_updates": [],
                    "final_answers": ["ok"],
                }
            )
            revision_id, revision_dir, audit = ingest_revision(
                distill_dir,
                session_id="abc",
                platform="test",
                turns=turns,
                source_fingerprint={"size_bytes": 123},
                metadata={"name": "demo"},
            )
            self.assertEqual(audit["coverage"], "lossless")
            ok, message = verify_revision_rebuild(revision_dir)
            self.assertTrue(ok, message)
            manifest = json.loads((revision_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["revision_id"], revision_id)
            self.assertGreaterEqual(manifest["chunk_count"], 1)

    def test_chunks_split_large_sessions_without_losing_turns(self):
        turns = []
        for index in range(20):
            turns.append(
                {
                    "turn_id": f"t{index}",
                    "user_messages": ["u" * 4000],
                    "assistant_updates": ["a" * 4000],
                    "final_answers": [],
                }
            )
        chunks = split_turns_into_chunks(turns, max_chars=10_000)
        self.assertGreater(len(chunks), 1)
        rebuilt = []
        for chunk in chunks:
            rebuilt.extend(chunk["turns"])
        self.assertEqual(len(rebuilt), len(turns))

    def test_distilled_growth_reopens_queue(self):
        old = {
            "status": "distilled",
            "last_distilled_revision_id": "rev-old",
            "last_indexed_fingerprint": "fp-old",
        }
        status = compute_queue_status_on_index(
            old,
            source_fingerprint="fp-new",
            current_revision_id="rev-new",
        )
        self.assertEqual(status, "pending_redistill")
        self.assertTrue(needs_redistill({**old, "current_revision_id": "rev-new"}, "rev-new"))

    def test_candidate_id_is_idempotent(self):
        claim = normalize_claim("  Verify   Payment  Flow ")
        a = make_candidate_id(source_revision_id="rev1", candidate_kind="memory_draft", normalized_claim=claim)
        b = make_candidate_id(source_revision_id="rev1", candidate_kind="memory_draft", normalized_claim=claim)
        self.assertEqual(a, b)

    def test_final_review_validation(self):
        good = (
            "## Final Session Review\n"
            "- **Final user request:** fix queue\n"
            "- **Final outcome:** fixed\n"
            "- **Last turn state:** completed\n"
            "- **Contradictions:** none\n"
            "- **Open items:** none\n"
            "- **Evidence status:** all ANSWERED\n"
            "- **Promotion allowed:** yes\n"
        )
        self.assertEqual(validate_final_review(good), [])
        self.assertTrue(promotion_allowed(good))
        unverified = good.replace("all ANSWERED", "not verified")
        self.assertIn("Promotion allowed: yes requires Evidence status: all ANSWERED", promotion_blocked_reasons(unverified))
        self.assertFalse(promotion_allowed(unverified))
        bad = "## Promotion Decision\n\nNo promotion\n"
        self.assertTrue(validate_final_review(bad))

    def test_messages_to_turns_preserves_full_unknown_role_content(self):
        content = "x" * 1000
        turns = messages_to_turns([{"role": "system", "content": content}])
        self.assertEqual(turns[0]["system_events"], [f"system: {content}"])

    def test_chunked_extract_resumes_without_reprocessing(self):
        import deep_distill_lib as ddl
        from distill_core.deep_run import extract_claims_chunked

        with tempfile.TemporaryDirectory() as tmp:
            distill_dir = Path(tmp)
            turns = _sample_turns("chunk-resume")
            revision_id, revision_dir, _audit = ingest_revision(
                distill_dir,
                session_id="resume-test",
                platform="test",
                turns=turns,
                source_fingerprint={"size_bytes": 1},
                metadata={"name": "resume"},
            )
            meta = {"session_id": "resume-test", "current_revision_id": revision_id}
            first, _stats1 = extract_claims_chunked(revision_dir, meta, ddl.extract_claims_from_turns)
            second, stats2 = extract_claims_chunked(revision_dir, meta, ddl.extract_claims_from_turns)
            self.assertEqual(first, second)
            self.assertGreaterEqual(stats2.get("chunks_resumed", 0), 1)
            self.assertEqual(stats2.get("chunks_processed", 0), 0)

    def test_chunk_lease_prevents_concurrent_extractors(self):
        from distill_core.deep_run import extract_claims_chunked

        with tempfile.TemporaryDirectory() as tmp:
            revision_id, revision_dir, _audit = ingest_revision(
                Path(tmp),
                session_id="lease-test",
                platform="test",
                turns=_sample_turns(),
                source_fingerprint={"size_bytes": 1},
            )
            started = threading.Event()
            release = threading.Event()
            calls: list[str] = []

            def extractor(_turns, _meta):
                calls.append("claimed")
                started.set()
                self.assertTrue(release.wait(timeout=5))
                return ["claim"]

            meta = {"session_id": "lease-test", "current_revision_id": revision_id}
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(extract_claims_chunked, revision_dir, meta, extractor)
                self.assertTrue(started.wait(timeout=5))
                second = pool.submit(extract_claims_chunked, revision_dir, meta, extractor)
                second_claims, second_stats = second.result(timeout=5)
                self.assertEqual(second_claims, [])
                self.assertEqual(second_stats["chunks_leased_elsewhere"], 1)
                release.set()
                first_claims, _first_stats = first.result(timeout=5)

            self.assertEqual(calls, ["claimed"])
            self.assertEqual(first_claims, ["claim"])


if __name__ == "__main__":
    unittest.main()
