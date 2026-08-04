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
  - `E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md` (canonical; `SESSION_DISTILL_KB` to override)

## Default Workflow

**Shallow (packet prep):**

1. Run `python ~/.grok/skills/session-distill/bin/grok-session-distill.py run --next 1`.
2. Read the generated packet and inspect `Packet Audit` first.

**Deep (servers backlog — preferred):**

1. `python ~/.grok/skills/session-distill/bin/deep-distill-run.py --batch-size 3 --offset N`
2. For each session, complete `distilled/answer-packets/<id>.md` using **answer-me** + toolchain (`Grep`/`Read`/`git`/`Shell`; optional `mcp-search`).
3. Promote **only** `ANSWERED` rows → canonical `session-knowledge-base.md` (§I) / `docs/` / `AGENTS.md` / steering.
4. Run **check-work** subagent on promotion diffs; on `VERDICT: FAIL`, fix or demote before closing batch.
5. Write `distilled/sessions/<session-id>.md` with promotion decision.
6. `mark <session-id> distilled`.

See `references/deep-distill-workflow.md` and `references/distillation-rules.md`. Chat history is never evidence.

Unlike Codex, Grok keeps live session state under `~/.grok/sessions`.
`mark distilled` keeps raw files by default. Use `--delete-raw` only when you
intentionally want to remove `chat_history.jsonl` after review.

## Slash Command Routing

`/session-distill` should behave like Cursor's `.cursor/commands/session-distill.md`:

- script subcommands (`status`, `run`, `list`, `mark`, `index`) -> run the Python CLI directly
- no args -> `status`
- natural language -> `run --next 3` first, then read packets and distill

Default scope is **all projects** under `~/.grok/sessions/`.
Use `--project <keyword>` only to narrow to one repo.

See `commands/session-distill.md` for the user-invocable slash command definition.

## Commands

```bash
python ~/.grok/skills/session-distill/bin/grok-session-distill.py status
python ~/.grok/skills/session-distill/bin/grok-session-distill.py list --size 0
python ~/.grok/skills/session-distill/bin/grok-session-distill.py run --next 3
python ~/.grok/skills/session-distill/bin/grok-session-distill.py run --project servers --next 3
python ~/.grok/skills/session-distill/bin/grok-session-distill.py mark <session-id> distilled
python ~/.grok/skills/session-distill/bin/grok-session-distill.py mark <session-id> distilled --delete-raw
python ~/.grok/skills/session-distill/bin/grok-session-distill.py self-test
```

## References

- `references/grok-session-format.md`: Grok JSONL event shapes and packet rules.
- `references/distillation-rules.md`: promotion and filtering rules.
- `references/output-layout.md`: workspace layout and status meanings.

Use the Claude / Codex / Cursor distillers only for their respective session roots.