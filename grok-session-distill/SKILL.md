---
name: session-distill
description: |
  Distill Grok CLI session JSONL files into review packets, local session notes,
  and reusable memory candidates. Use when the user asks to整理/提炼 Grok
  对话, runs /session-distill, processes `~/.grok/sessions` chat history,
  generates session packets, reviews packet coverage, or marks Grok sessions
  as distilled.
argument-hint: "[status | run --next N | list | mark <id> distilled]"
user-invocable: true
---

# Grok Session Distiller

This is the Grok-native `session-distill` skill. It reads Grok CLI
`chat_history.jsonl`, not Claude Code / Codex / Cursor session files.

## Inputs And Outputs

- Input sessions:
  - `~/.grok/sessions/<encoded-project>/<session-id>/chat_history.jsonl`
  - `~/.grok/sessions/<encoded-project>/<session-id>/summary.json` for metadata
- Workspace:
  - `~/.grok/session-distill/manifest.json`
  - `~/.grok/session-distill/packets/<session-id>.md`
  - `~/.grok/session-distill/distilled/sessions/<session-id>.md`
  - `~/.grok/session-distill/knowledge-base.md`

## Default Workflow (Deep Distill)

Follow `references/deep-distill-workflow.md` (Grok paradigm, shared across platforms):

1. `python bin/deep-distill-run.py --batch-size 3` — bundle + extract claims → `distilled/answer-packets/`
2. answer-me: verify each Q with Read/Grep/git/Shell; only `ANSWERED` promotes
3. Session note under `distilled/sessions/<session-id>.md`
4. `distilled/check-work/batch-*-report.md` with promoted / not-promoted reasons
5. `mark <session-id> distilled` after check-work PASS

Legacy one-shot flow (`run --next 1` without answer-packets) is for packet preview only — do not auto-promote to KB.

## Packet Preview (optional)

1. Run `python bin/grok-session-distill.py run --next 1`.
2. Read the generated packet and inspect `Packet Audit` first.
3. If `Coverage: partial`, inspect the raw `chat_history.jsonl` span before promoting any conclusion.

Unlike Codex, Grok keeps live session state under `~/.grok/sessions`.
`mark distilled` keeps raw files by default. Use `--delete-raw` only when you
intentionally want to remove `chat_history.jsonl` after review.

## Slash Command Routing

`/session-distill` routes per `commands/session-distill.md`:

- `deep-distill` or「蒸馏下一批」→ `deep-distill-run.py --batch-size 3`
- script subcommands (`status`, `run`, `list`, `mark`, `index`) → Python CLI directly
- no args → `status` + queue summary
- natural language → prefer `deep-distill-run.py` over bulk auto-promote

Default scope is **all projects** under `~/.grok/sessions/`.
Use `--project <keyword>` only to narrow to one repo.

## Commands

```bash
python ~/.grok/skills/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3
python ~/.grok/skills/session-distill/bin/grok-session-distill.py status
python ~/.grok/skills/session-distill/bin/grok-session-distill.py list --size 0
python ~/.grok/skills/session-distill/bin/grok-session-distill.py run --next 3
python ~/.grok/skills/session-distill/bin/grok-session-distill.py run --project servers --next 3
python ~/.grok/skills/session-distill/bin/grok-session-distill.py mark <session-id> distilled
python ~/.grok/skills/session-distill/bin/grok-session-distill.py mark <session-id> distilled --delete-raw
python ~/.grok/skills/session-distill/bin/grok-session-distill.py self-test
```

## References

- `references/deep-distill-workflow.md`: canonical Deep Distill pipeline (all platforms).
- `references/grok-session-format.md`: Grok JSONL event shapes and packet rules.
- `references/distillation-rules.md`: promotion and filtering rules.
- `references/output-layout.md`: workspace layout and status meanings.

Use the Claude / Codex / Cursor distillers only for their respective session roots.