# Output Layout

Codex `session-distill` uses `~/.codex/session-distill`.

- `manifest.json`: indexed sessions and processing status.
- `packets/<session-id>.md`: low-noise packet generated from Codex rollout JSONL.
- `distilled/answer-packets/<session-id>.md`: Deep Distill claims + verification table.
- `distilled/check-work/batch-offset-*.md`: batch promotion audit reports.
- `servers-deep-queue.md`: servers-only queue progress.
- `distilled/sessions/<session-id>.md`: human/AI session note after packet review.
- `knowledge-base.md`: stable cross-session knowledge.
- `memory-drafts/<session-id>.json`: optional reviewed draft entries.

Statuses:

- `new`: indexed, no packet prepared yet.
- `bundled`: packet prepared and waiting for review.
- `distilled`: packet reviewed, note written, promotion decision recorded.
- `skipped`: intentionally excluded.

`distilled` is guarded. A session note is required, and partial packets must
show that raw JSONL was reviewed before promotion. After a successful
`mark ... distilled`, the raw Codex rollout JSONL is retained. Raw deletion is
an explicit, audited `prune-raw <session-id> --confirm --reason "..."` operation.
The manifest preserves distilled records whose raw source has already been deleted.
