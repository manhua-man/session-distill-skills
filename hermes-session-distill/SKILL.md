---
name: session-distill
description: |
  Distill Hermes Agent SQLite sessions into review packets, local session notes,
  and reusable memory candidates. Use when the user asks to整理/提炼 Hermes
  对话, process `%LOCALAPPDATA%\hermes\state.db`, generate session packets,
  review packet coverage, or mark Hermes sessions as distilled.
argument-hint: "[status | run --next N | deep-distill | mark <id> distilled]"
user-invocable: true
---

# Hermes Session Distiller

This is the Hermes-native `session-distill` skill. It reads Hermes `state.db`
(SQLite), not Claude Code / Codex / Cursor session files.

## Inputs And Outputs

- Input sessions:
  - `%LOCALAPPDATA%\hermes\state.db` (override: `HERMES_STATE_DB`)
  - optional `HERMES_HOME` when not under default LocalAppData path
- Workspace:
  - `%LOCALAPPDATA%\hermes\session-distill\manifest.json`
  - `%LOCALAPPDATA%\hermes\session-distill\packets\<session-id>.md`
  - `%LOCALAPPDATA%\hermes\session-distill\distilled\sessions\<session-id>.md`
  - `%LOCALAPPDATA%\hermes\session-distill\knowledge-base.md`
  - optional `%LOCALAPPDATA%\hermes\session-distill\memory-drafts\<session-id>.json`

## Default Workflow (Deep Distill)

Follow `references/deep-distill-workflow.md` (shared across platforms):

1. `python bin/deep-distill-run.py --batch-size 3` — bundle + extract claims → `distilled/answer-packets/`
2. answer-me: verify each Q with Read/Grep/git/Shell; only `ANSWERED` promotes
3. Session note under `distilled/sessions/<session-id>.md`
4. `distilled/check-work/batch-*-report.md` with promoted / not-promoted reasons
5. `mark <session-id> distilled` after check-work PASS

Legacy one-shot flow (`run --next 1` without answer-packets) is for packet preview only — do not auto-promote to KB.

## Packet Preview (optional)

1. Run `python bin/hermes-session-distill.py run --next 1`.
2. Read the generated packet and inspect `Packet Audit` first.
3. If `Coverage: partial`, inspect the raw SQLite conversation span before promoting any conclusion.

`mark distilled` requires a session note and promotion decision. Partial packets must document raw DB review.

## Commands

```powershell
$env:HERMES_DISTILL_DIR = "$env:LOCALAPPDATA\hermes\session-distill"

python $env:LOCALAPPDATA\hermes\skills\session-distill\bin\deep-distill-run.py --offset 0 --batch-size 3
python $env:LOCALAPPDATA\hermes\skills\session-distill\bin\hermes-session-distill.py status
python $env:LOCALAPPDATA\hermes\skills\session-distill\bin\hermes-session-distill.py list --size 100
python $env:LOCALAPPDATA\hermes\skills\session-distill\bin\hermes-session-distill.py run --next 1
python $env:LOCALAPPDATA\hermes\skills\session-distill\bin\hermes-session-distill.py mark <session-id> distilled
python $env:LOCALAPPDATA\hermes\skills\session-distill\bin\hermes-session-distill.py self-test
```

## References

- `references/deep-distill-workflow.md`: canonical Deep Distill pipeline (all platforms).
- `references/distillation-rules.md`: promotion and filtering rules.
- `references/output-layout.md`: workspace layout and status meanings.

Use other platform distillers only for their respective session roots.
