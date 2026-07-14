---
description: Claude Deep Distill — Grok 范式（3 条/批，answer-me 验证后晋升）
argument-hint: "[deep-distill | status | run --next N | mark <id> distilled]"
user-invocable: true
---

Use the **Claude Deep Distill** workflow (same paradigm as Grok / Cursor / Codex).

Always load:

- `~/.claude/skills/manhua/session-distill/SKILL.md`
- `~/.claude/skills/manhua/session-distill/references/deep-distill-workflow.md`
- `~/.claude/skills/manhua/session-distill/references/distillation-rules.md`

## Mental model

```
Claude JSONL → packet → answer-packet (claims + verify) → session note → KB (ANSWERED only)
```

## Command routing

| Input | Action |
|-------|--------|
| `deep-distill` or「蒸馏下一批」 | `deep-distill-run.py --batch-size 3` then answer-me + check-work |
| `status` / `list` / `run` / `mark` | `session-distill.py <cmd>` |
| (empty) | `status` + queue summary from `servers-deep-queue.md` |

```bash
python ~/.claude/skills/manhua/session-distill/bin/deep-distill-run.py --offset <N> --batch-size 3
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py status
```

## Distillation (mandatory phases)

1. `deep-distill-run.py` → refresh packets + `distilled/answer-packets/`
2. answer-me: verify each Q with Read/Grep/git/Shell; only `ANSWERED` promotes
3. Session note + optional `knowledge-base.md` / repo `session-knowledge-base.md`
4. `distilled/check-work/batch-*-report.md` with promoted / not-promoted reasons
5. `mark distilled` after check-work PASS

## Guardrails

- Chat/packet ≠ evidence.
- No `auto-run` / `auto-standalone` bulk promote without answer-packets.
- `Coverage: partial` → read raw `.jsonl` before closing Q rows.
