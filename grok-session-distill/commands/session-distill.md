---
description: Grok Deep Distill — 全平台统一范式（3 条/批，answer-me 验证后晋升）
argument-hint: "[deep-distill | status | run --next N | mark <id> distilled]"
user-invocable: true
---

Use the **Grok Deep Distill** workflow (same paradigm as Cursor / Codex / Claude).

Always load:

- `~/.grok/skills/session-distill/SKILL.md`
- `~/.grok/skills/session-distill/references/deep-distill-workflow.md`
- `~/.grok/skills/session-distill/references/distillation-rules.md`

## Mental model

```
chat_history.jsonl → packet → answer-packet (claims + verify) → session note → KB (ANSWERED only)
```

## Command routing

| Input | Action |
|-------|--------|
| `deep-distill` or「蒸馏下一批」 | `deep-distill-run.py --batch-size 3` then answer-me + check-work |
| `status` / `list` / `run` / `mark` | `grok-session-distill.py <cmd>` |
| (empty) | `status` + queue summary from `servers-deep-queue.md` |

```powershell
python $env:USERPROFILE\.grok\skills\session-distill\bin\deep-distill-run.py --offset <N> --batch-size 3
python $env:USERPROFILE\.grok\skills\session-distill\bin\grok-session-distill.py status
```

## Distillation (mandatory phases)

1. `deep-distill-run.py` → refresh packets + `distilled/answer-packets/`
2. answer-me: verify each Q with Read/Grep/git/Shell; only `ANSWERED` promotes
3. Session note + optional `knowledge-base.md` / repo `session-knowledge-base.md`
4. `distilled/check-work/batch-*-report.md` with promoted / not-promoted reasons
5. `mark distilled` after check-work PASS

## Guardrails

- Chat/packet ≠ evidence.
- Do not use deprecated `distill-servers-batch.py` for promotion.
- `Coverage: partial` → read raw `chat_history.jsonl` before closing Q rows.
