---
name: session-distill
description: |
  Distill OpenCode storage sessions into review packets, local session notes,
  and reusable memory candidates. Use when the user asks to整理/提炼 OpenCode
  对话, process `~/.local/share/opencode/storage/`, generate session packets,
  review packet coverage, or mark OpenCode sessions as distilled.
argument-hint: "[status | run --next N | deep-distill | mark <id> distilled]"
user-invocable: true
---

# OpenCode Session Distiller

This is the OpenCode-native `session-distill` skill. It reads OpenCode storage
JSON trees under `storage/session`, not Claude Code / Codex / Cursor files.

## Inputs And Outputs

- Input sessions:
  - `~/.local/share/opencode/storage/session/**`
  - `~/.local/share/opencode/storage/message/**` and `storage/part/**` for message bodies
  - override home: `OPENCODE_HOME`
- Workspace:
  - `~/.local/share/opencode/session-distill/manifest.json`
  - `~/.local/share/opencode/session-distill/packets/<session-id>.md`
  - `~/.local/share/opencode/session-distill/distilled/sessions/<session-id>.md`
  - `~/.local/share/opencode/session-distill/knowledge-base.md`

## Default Workflow (Deep Distill)

Follow `references/deep-distill-workflow.md` (shared across platforms):

1. `python bin/deep-distill-run.py --batch-size 3` — bundle + extract claims → `distilled/answer-packets/`
2. answer-me: verify each Q with Read/Grep/git/Shell; only `ANSWERED` promotes
3. Session note under `distilled/sessions/<session-id>.md`
4. `distilled/check-work/batch-*-report.md` with promoted / not-promoted reasons
5. `mark <session-id> distilled` after check-work PASS

Legacy one-shot flow (`run --next 1` without answer-packets) is for packet preview only — do not auto-promote to KB.

## Packet Preview (optional)

1. Run `python bin/opencode-session-distill.py run --next 1`.
2. Read the generated packet and inspect `Packet Audit` first.
3. If `Coverage: partial`, inspect raw storage JSON before promoting any conclusion.

`mark distilled` requires a session note and promotion decision. Partial packets must document raw storage review.

## Commands

```bash
export OPENCODE_DISTILL_DIR="$HOME/.local/share/opencode/session-distill"

python ~/.config/opencode/skills/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3
python ~/.config/opencode/skills/session-distill/bin/opencode-session-distill.py status
python ~/.config/opencode/skills/session-distill/bin/opencode-session-distill.py list --size 100
python ~/.config/opencode/skills/session-distill/bin/opencode-session-distill.py run --next 1
python ~/.config/opencode/skills/session-distill/bin/opencode-session-distill.py mark <session-id> distilled
python ~/.config/opencode/skills/session-distill/bin/opencode-session-distill.py self-test
```

## References

- `references/deep-distill-workflow.md`: canonical Deep Distill pipeline (all platforms).
- `references/distillation-rules.md`: promotion and filtering rules.
- `references/output-layout.md`: workspace layout and status meanings.

Use other platform distillers only for their respective session roots.
