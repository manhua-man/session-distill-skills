# Output Layout (Cursor)

Workspace: `~/.cursor/session-distill/` (`CURSOR_DISTILL_DIR`)

| Path | Purpose |
|------|---------|
| `cursor-manifest.json` | Indexed Composer sessions + status |
| `servers-deep-queue.md` | Deep Distill batch progress (3 sessions/batch) |
| `packets/cursor-<session-id>.md` | Low-noise packet (high clip limits) |
| `distilled/answer-packets/<session-id>.md` | answer-me verification log |
| `distilled/sessions/<session-id>.md` | Session note after review |
| `distilled/check-work/batch-*-report.md` | Promotion audit per batch |
| `knowledge-base.md` | Local workspace KB (optional) |

Repo canonical KB: `E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md`

## Statuses

- `new` — indexed, no packet
- `bundled` — packet ready for Deep Distill
- `distilled` — answer-me complete, promotion recorded, `mark` passed
- `skipped` — intentionally excluded

`mark distilled` requires session note + promotion decision. Partial packets must document raw JSONL review.

Raw transcripts: `~/.cursor/projects/<project>/agent-transcripts/<id>/<id>.jsonl` — kept by default.
