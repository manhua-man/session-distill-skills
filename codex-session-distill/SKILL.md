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

## Default Workflow (Deep Distill)

Follow `references/deep-distill-workflow.md` (shared across Grok / Cursor / Codex / Claude):

1. `python bin/deep-distill-run.py --batch-size 3` — bundle + extract claims → `distilled/answer-packets/`
2. answer-me: verify each Q with Read/Grep/git/Shell; only `ANSWERED` promotes
3. Session note under `distilled/sessions/<session-id>.md`
4. `distilled/check-work/batch-*-report.md` with promoted / not-promoted reasons
5. `mark <session-id> distilled` after check-work PASS

Legacy one-shot flow (`run --next 1` without answer-packets) is for packet preview only — do not auto-promote to KB.

## Packet Preview (optional)

1. Run `python ~/.codex/skills/manhua/session-distill/bin/session-distill.py run --next 1`.
2. Read the generated packet and inspect `Packet Audit` first.
3. If `Coverage: partial`, inspect the raw JSONL span before promoting any conclusion.

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

- `references/deep-distill-workflow.md`: canonical Deep Distill pipeline (all platforms).
- `references/codex-session-format.md`: Codex JSONL event shapes and packet rules.
- `references/distillation-rules.md`: promotion and filtering rules.
- `references/output-layout.md`: workspace layout and status meanings.

Use the older Claude session distiller only for `~/.claude/projects/*.jsonl`.
