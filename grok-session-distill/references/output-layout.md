# Output Layout

Grok `session-distill` uses `~/.grok/session-distill`.

- `manifest.json`: indexed sessions and processing status.
- `packets/<session-id>.md`: low-noise packet generated from `chat_history.jsonl`.
- `distilled/sessions/<session-id>.md`: human/AI session note after packet review.
- `knowledge-base.md`: stable cross-session knowledge.

Statuses:

- `new`: indexed, no packet prepared yet.
- `bundled`: packet prepared and waiting for review.
- `distilled`: packet reviewed, note written, promotion decision recorded.
- `skipped`: intentionally excluded.

`distilled` is guarded. A session note is required, and partial packets must
show that raw `chat_history.jsonl` was reviewed before promotion. After a
successful `mark ... distilled`, Grok raw files are kept by default. Use
`--delete-raw` only when you intentionally want to remove `chat_history.jsonl`.
The manifest preserves distilled records whose raw source has already been deleted.