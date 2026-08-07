# Output Directory Layout (All Platforms)

Default workspace layout under `~/.<platform>/session-distill/`:

| Path | Purpose |
|------|---------|
| `<platform>-manifest.json` | Indexed sessions overview (rebuild via `index`) |
| `packets/<platform>-<session-id>.md` | Low-noise packet (high clip limits); **exists ⇒ already processed (dedup)** |
| `distilled/answer-packets/<session-id>.md` | answer-me verification log |
| `distilled/sessions/<session-id>.md` | Session note after review |
| `distilled/check-work/batch-*-report.md` | Promotion audit per batch |

Repo canonical KB: `E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md`

## Stateless notes

- No queue-progress file and no `mark distilled` bookkeeping: batches are picked by
  `deep-distill-run.py --project <p>`, skipping sessions whose packet already exists.
- `manifest.status` is informational only (set by `index`); it is not used for batch picking.

Raw transcripts are kept by default per platform specification.
