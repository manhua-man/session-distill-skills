---
name: session-distill
description: |
  Cursor Composer 会话 Deep Distill：packet → answer-me 验证 → session note → KB。
  处理范式与 Grok 一致；禁止无验证的批量晋升。
argument-hint: "[status | run --next N | deep-distill | mark <id> distilled]"
---

# Cursor Session Distiller (Deep Distill)

Reads Cursor SQLite + JSONL agent transcripts. **Default paradigm: Grok Deep Distill** (3 sessions/batch).

## Workspace

- Input: `~/.cursor/projects/<project>/agent-transcripts/<id>/<id>.jsonl`
- Workdir: `~/.cursor/session-distill/` (`CURSOR_DISTILL_DIR`)
- Repo KB: `E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md`

## Default Workflow (servers)

```powershell
$env:CURSOR_DISTILL_DIR = "$env:USERPROFILE\.cursor\session-distill"

# 1. Queue status
python .cursor/skills/session-distill/bin/cursor-session-distill.py list --project servers

# 2. Deep batch (3 sessions): bundle + extract claims → answer-packets
python .cursor/skills/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3

# 3. AI: answer-me verify each Q (Grep/Read/git/Shell) → fill answer-packet Results

# 4. Write session note + promote ANSWERED only → session-knowledge-base.md

# 5. check-work report → mark distilled
python .cursor/skills/session-distill/bin/cursor-session-distill.py mark <session-id> distilled
```

## References (load before distilling)

- `references/deep-distill-workflow.md` — canonical pipeline
- `references/distillation-rules.md` — promotion gates
- `references/output-layout.md` — paths and statuses

## Anti-patterns

- Do **not** use bulk auto-promote scripts without answer-packets.
- Do **not** promote from packet text alone when `Coverage: partial`.
- Chat history is hypotheses until toolchain verification.

## Low-level CLI

```powershell
python .cursor/skills/session-distill/bin/cursor-session-distill.py status
python .cursor/skills/session-distill/bin/cursor-session-distill.py run --next 1
python .cursor/skills/session-distill/bin/cursor-session-distill.py mark <id> distilled
```
