# Output Layout

OpenCode `session-distill` uses `~/.local/share/opencode/session-distill` (`OPENCODE_DISTILL_DIR`).

| Path | Purpose |
|------|---------|
| `manifest.json` | Indexed sessions and processing status |
| `servers-deep-queue.md` | Deep Distill batch progress (3 sessions/batch) |
| `packets/<session-id>.md` | Low-noise packet from storage JSON |
| `distilled/answer-packets/<session-id>.md` | Claims + answer-me Results table (promotion gate) |
| `distilled/sessions/<session-id>.md` | Session note after verification |
| `distilled/check-work/batch-*-report.md` | Promotion audit per batch |
| `knowledge-base.md` | Stable cross-session knowledge (ANSWERED only) |

Statuses:

- `new`: indexed, no packet prepared yet.
- `bundled`: packet ready for Deep Distill.
- `distilled`: answer-packet verified, note written, check-work PASS, promotion recorded.
- `skipped`: intentionally excluded.

`distilled` is guarded. Answer-packet must exist; partial packets must show raw storage JSON was reviewed. Only `ANSWERED` rows may promote to KB.

Raw source: `~/.local/share/opencode/storage/` — kept by default.

Skill install path: `~/.config/opencode/skills/session-distill/`.
