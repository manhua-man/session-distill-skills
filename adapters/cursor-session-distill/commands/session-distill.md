---
description: Cursor Deep Distill — Grok 范式（3 条/批，answer-me 验证后晋升）
argument-hint: "[deep-distill | status | run --next N | mark <id> distilled]"
---

Use the **Cursor Deep Distill** workflow (same paradigm as Grok).

Always load:

- `.cursor/skills/session-distill/SKILL.md`
- `.cursor/skills/session-distill/references/deep-distill-workflow.md`
- `.cursor/skills/session-distill/references/distillation-rules.md`

## Mental model

```
JSONL/SQLite → packet → answer-packet (claims + verify) → session note → KB (ANSWERED only)
```

## Command routing

| Input | Action |
|-------|--------|
| `deep-distill` or natural language「蒸馏下一批」 | `deep-distill-run.py --batch-size 3` then phases 3–7 |
| `status` / `list` / `run` / `mark` | `cursor-session-distill.py <cmd>` |
| (empty) | `status` + summarize queue + suggest next `deep-distill` offset |

```powershell
$env:CURSOR_DISTILL_DIR = "$env:USERPROFILE\.cursor\session-distill"
python .cursor/skills/session-distill/bin/cursor-session-distill.py status
python .cursor/skills/session-distill/bin/deep-distill-run.py --offset <N> --batch-size 3
```

## Distillation behavior (mandatory)

1. Run `deep-distill-run.py` to refresh packets + create `answer-packets/`.
2. For each claim row: verify with Read/Grep/git/Shell; set Status `ANSWERED` only when proven.
3. Write `distilled/sessions/<id>.md` + update `session-knowledge-base.md` §Cursor Deep Distill.
4. Complete `distilled/check-work/batch-*-report.md` (promoted / not promoted + reasons).
5. `mark distilled` only after check-work PASS.

## Guardrails

- Chat/packet ≠ evidence.
- No bulk promotion without answer-me table.
- Partial coverage → read raw JSONL under `agent-transcripts/`.
