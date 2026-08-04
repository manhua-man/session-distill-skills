---
name: session-distill
description: |
  Distill Antigravity CLI sessions into review packets, local session notes,
  and reusable memory candidates. Use when the user asks to整理/提炼 Antigravity
  对话, process `~/.gemini/antigravity-cli/history.jsonl` and brain transcripts,
  generate session packets, review packet coverage, or mark sessions as distilled.
argument-hint: "[status | run --next N | deep-distill | mark <id> distilled]"
user-invocable: true
---

# Antigravity Session Distiller

This is the Antigravity-native `session-distill` skill. It reads
`history.jsonl` plus `brain/` transcripts, not Claude Code / Codex / Cursor files.

## Inputs And Outputs

- Input sessions:
  - `~/.gemini/antigravity-cli/history.jsonl` or `~/.gemini/antigravity/history.jsonl`
  - `~/.gemini/antigravity-cli/brain/**` / `~/.gemini/antigravity/brain/**` (conversation transcripts)
  - override root: `ANTIGRAVITY_CLI_ROOT`, `AGY_HOME`, or `ANTIGRAVITY_HOME`
- Workspace:
  - `~/.gemini/antigravity-cli/session-distill/manifest.json`
  - `~/.gemini/antigravity-cli/session-distill/packets/<session-id>.md`
  - `~/.gemini/antigravity-cli/session-distill/distilled/sessions/<session-id>.md`
  - `~/.gemini/antigravity-cli/session-distill/knowledge-base.md`

## Default Workflow (Deep Distill)

Follow `references/deep-distill-workflow.md` (shared across platforms):

1. `python bin/deep-distill-run.py --batch-size 3` — bundle + extract claims → `distilled/answer-packets/`
2. answer-me: verify each Q with Read/Grep/git/Shell; only `ANSWERED` promotes
3. Session note under `distilled/sessions/<session-id>.md`
4. `distilled/check-work/batch-*-report.md` with promoted / not-promoted reasons
5. `mark <session-id> distilled` after check-work PASS

Legacy one-shot flow (`run --next 1` without answer-packets) is for packet preview only — do not auto-promote to KB.

## Packet Preview (optional)

1. Run `python bin/antigravity-session-distill.py run --next 1`.
2. Read the generated packet and inspect `Packet Audit` first.
3. If `Coverage: partial`, inspect raw `history.jsonl` / brain transcript spans before promoting.

`mark distilled` requires a session note and promotion decision. Partial packets must document raw transcript review.

## Commands

```bash
export AGY_DISTILL_DIR="$HOME/.gemini/antigravity-cli/session-distill"

python ~/.gemini/antigravity-cli/skills/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3
python ~/.gemini/antigravity-cli/skills/session-distill/bin/antigravity-session-distill.py status
python ~/.gemini/antigravity-cli/skills/session-distill/bin/antigravity-session-distill.py list --size 100
python ~/.gemini/antigravity-cli/skills/session-distill/bin/antigravity-session-distill.py run --next 1
python ~/.gemini/antigravity-cli/skills/session-distill/bin/antigravity-session-distill.py mark <session-id> distilled
python ~/.gemini/antigravity-cli/skills/session-distill/bin/cleanup-antigravity-distill.py all
python ~/.gemini/antigravity-cli/skills/session-distill/bin/antigravity-session-distill.py self-test
```

## References

- `references/deep-distill-workflow.md`: canonical Deep Distill pipeline (all platforms).
- `references/distillation-rules.md`: promotion and filtering rules.
- `references/output-layout.md`: workspace layout and status meanings.

Use other platform distillers only for their respective session roots.
