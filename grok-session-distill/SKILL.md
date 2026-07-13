---
name: session-distill
description: |
  Distill Grok CLI session JSONL files into review packets, local session notes,
  and reusable memory candidates. Use when the user asks to整理/提炼 Grok
  对话, process `~/.grok/sessions` chat history, generate session packets,
  review packet coverage, or mark Grok sessions as distilled.
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

## Default Workflow

1. Run `python ~/.grok/skills/session-distill/bin/grok-session-distill.py run --next 1`.
2. Read the generated packet and inspect `Packet Audit` first.
3. If `Coverage: partial`, inspect the raw `chat_history.jsonl` span before promoting any conclusion.
4. Write a session note under `distilled/sessions/<session-id>.md`.
5. Append only stable reusable knowledge to `knowledge-base.md`, or explicitly record no promotion.
6. Run `python ~/.grok/skills/session-distill/bin/grok-session-distill.py mark <session-id> distilled`.

Unlike Codex, Grok keeps live session state under `~/.grok/sessions`.
`mark distilled` keeps raw files by default. Use `--delete-raw` only when you
intentionally want to remove `chat_history.jsonl` after review.

## Commands

```bash
python ~/.grok/skills/session-distill/bin/grok-session-distill.py status
python ~/.grok/skills/session-distill/bin/grok-session-distill.py list --size 0
python ~/.grok/skills/session-distill/bin/grok-session-distill.py run --next 1
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