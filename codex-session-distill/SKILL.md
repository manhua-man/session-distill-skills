---
name: session-distill
description: |
  Distill Codex session JSONL files into review packets, local session notes,
  and reusable memory candidates. Use when the user asks to整理/提炼 Codex
  对话, process `.codex/archived_sessions` or `.codex/sessions` rollouts,
  generate session packets, review packet coverage, or mark Codex sessions as
  distilled.
---

# Codex Session Distiller

This is the Codex-native `session-distill` skill. It reads Codex rollout
JSONL, not Claude Code session files.

## Inputs And Outputs

- Input sessions:
  - `~/.codex/archived_sessions/rollout-*.jsonl`
  - `~/.codex/sessions/**/*.jsonl`
  - `~/.codex/session_index.jsonl` for thread names when available
- Workspace:
  - `~/.codex/session-distill/manifest.json`
  - `~/.codex/session-distill/packets/<session-id>.md`
  - `~/.codex/session-distill/distilled/sessions/<session-id>.md`
  - `~/.codex/session-distill/knowledge-base.md`
  - optional `~/.codex/session-distill/memory-drafts/<session-id>.json`

## Default Workflow

### Deep Distill (servers, recommended)

```powershell
python ~/.codex/skills/manhua/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3
```

Then: answer-me verify → promote ANSWERED only → `session-knowledge-base.md` §Codex → check-work → `mark distilled`.

See `references/deep-distill-workflow.md`.

### Legacy single-session flow

1. Run `python ~/.codex/skills/manhua/session-distill/bin/session-distill.py run --next 1`.
2. Read the generated packet and inspect `Packet Audit` first.
3. If `Coverage: partial`, inspect the raw JSONL span before promoting any conclusion.
4. Write a session note under `distilled/sessions/<session-id>.md`.
5. Append only stable reusable knowledge to `knowledge-base.md`, or explicitly record no promotion.
6. Before marking distilled, run a lightweight knowledge review when you promoted anything:
   `python ~/.codex/skills/manhua/session-distill/bin/session-distill.py review-kb --next 20 --query <session-id-or-topic>`
7. If memory drafts exist, review every entry so none remain `pending`.
8. Run `python ~/.codex/skills/manhua/session-distill/bin/session-distill.py mark <session-id> distilled`.
   This deletes the original Codex rollout JSONL after the guardrails pass, so
   the same session will not be re-discovered as pending work. Use `--keep-raw`
   only when you intentionally need to retain the raw transcript.

The `mark distilled` command has guardrails: it fails unless the note exists,
partial packets mention raw review, memory drafts have no pending entries, and
the note records a promotion decision. If `knowledge-base.md` already contains
entries sourced from the same session, obvious volatile or weak entries are also
rejected unless you use `--force`. Raw-file deletion still only applies under
`~/.codex/archived_sessions` or `~/.codex/sessions`.

## Commands

```bash
python ~/.codex/skills/manhua/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py status
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py list --size 100
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py run --next 1
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py mark <session-id> distilled
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py --keep-raw mark <session-id> distilled
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py review-kb --next 20
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py verify-entry <session-id|keyword>
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py prune-kb --statuses stale,superseded
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py self-test
```

## References

- `references/codex-session-format.md`: Codex JSONL event shapes and packet rules.
- `references/deep-distill-workflow.md`: Grok-paradigm batch pipeline for servers.
- `references/distillation-rules.md`: promotion and filtering rules.
- `references/output-layout.md`: workspace layout and status meanings.

Use the older Claude session distiller only for `~/.claude/projects/*.jsonl`.
