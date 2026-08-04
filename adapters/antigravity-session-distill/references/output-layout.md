# Output Layout

Antigravity `session-distill` uses `~/.gemini/antigravity-cli/session-distill` (`AGY_DISTILL_DIR`).

| Path | Purpose |
|------|---------|
| `manifest.json` | Indexed sessions and processing status |
| `servers-deep-queue.md` | Deep Distill batch progress (3 sessions/batch) |
| `packets/<session-id>.md` | Low-noise packet from history + brain transcripts |
| `distilled/answer-packets/<session-id>.md` | Claims + answer-me Results table (promotion gate) |
| `distilled/sessions/<session-id>.md` | Session note after verification |
| `distilled/check-work/batch-*-report.md` | Promotion audit per batch |
| `knowledge-base.md` | Stable cross-session knowledge (ANSWERED only) |

Statuses:

- `new`: indexed, no packet prepared yet.
- `bundled`: packet ready for Deep Distill.
- `distilled`: answer-packet verified, note written, check-work PASS, promotion recorded.
- `skipped`: intentionally excluded.

`distilled` is guarded. Answer-packet must exist; partial packets must show raw transcript review. Only `ANSWERED` rows may promote to KB.

Raw sources: `~/.gemini/antigravity-cli/history.jsonl`, `~/.gemini/antigravity-cli/brain/**` — kept by default.
