# Deep Distill Workflow (All Platforms)

Canonical processing paradigm for **Grok / Cursor / Codex / Claude / Hermes / Antigravity / OpenCode** session-distill.

## Principles

1. **Chat is hypotheses** — packets and transcripts are claim sources, not evidence.
2. **Toolchain before promotion** — every claim gets an `answer-me` row before KB/docs/AGENTS edits.
3. **Code > docs > chat** — on conflict, current repo wins; mark `stale` or `CONTRADICTED`.

## Pipeline (per batch of 3)

```
Phase 0  Queue      servers-deep-queue.md picks next 3 session IDs (chronological)
Phase 1  Ingest     platform distill bundle --force (refresh packets, high clip limits)
Phase 2  Extract    deep-distill-run.py → claims list per session
Phase 3  Verify     answer-me: fill Results table (Grep/Read/git/Shell)
Phase 4  Promote    ONLY Status=ANSWERED rows → repo session-knowledge-base.md (topic-classified by project domain, with verified date, no Source ID)
Phase 5  check-work Subagent or human replay evidence; FAIL → demote
Phase 6  Record     session note + answer-packet + optional docs/steering
Phase 7  Close      mark distilled; update queue progress
```

## Phase 3: answer-me verification (mandatory)

| Field | Content |
|-------|---------|
| ID | Q1, Q2, … |
| Lens | `repo` / `runtime` / `deploy` / `ai-entry` / `payment` / `auth` / `activity` |
| Status | `ANSWERED` / `PARTIAL` / `UNANSWERED` / `CONTRADICTED` / `NOT_APPLICABLE` |

**Only `ANSWERED` may promote.**

## Artifacts (per platform workspace)

```
~/.{grok,cursor,codex,claude,hermes,gemini/antigravity-cli,local/share/opencode}/session-distill/
  servers-deep-queue.md
  packets/
  distilled/
    answer-packets/<session-id>.md
    sessions/<session-id>.md
    check-work/batch-N-report.md
E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md
```

Hermes Windows default: `%LOCALAPPDATA%\hermes\session-distill\`
Antigravity: `%USERPROFILE%\.gemini\antigravity-cli\session-distill\`

## Runners

| Platform | Bundle CLI | Deep batch runner |
|----------|------------|-------------------|
| Grok | `grok-session-distill.py` | `deep-distill-run.py` |
| Cursor | `cursor-session-distill.py` | `deep-distill-run.py` |
| Codex | `session-distill.py` | `deep-distill-run.py` |
| Claude | `session-distill.py` | `deep-distill-run.py` |
| Hermes | `hermes-session-distill.py` | `deep-distill-run.py` |
| Antigravity | `antigravity-session-distill.py` | `deep-distill-run.py` |
| OpenCode | `opencode-session-distill.py` | `deep-distill-run.py` |

```powershell
# Cursor (servers repo)
$env:CURSOR_DISTILL_DIR = "$env:USERPROFILE\.cursor\session-distill"
python .cursor/skills/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3

# Grok
python $env:USERPROFILE\.grok\skills\session-distill\bin\deep-distill-run.py --offset 0 --batch-size 3

# Codex
python $env:USERPROFILE\.codex\skills\manhua\session-distill\bin\deep-distill-run.py --offset 0 --batch-size 3

# Claude Code
python ~/.claude/skills/manhua/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3

# Hermes
python $env:LOCALAPPDATA\hermes\skills\session-distill\bin\deep-distill-run.py --offset 0 --batch-size 3

# Antigravity
python $env:USERPROFILE\.gemini\antigravity-cli\skills\session-distill\bin\deep-distill-run.py --offset 0 --batch-size 3

# OpenCode
python $env:USERPROFILE\.config\opencode\skills\session-distill\bin\deep-distill-run.py --offset 0 --batch-size 3
```

Then on every platform: answer-me verify → promote ANSWERED only → check-work → mark distilled.

## Anti-patterns (do not use)

- Bulk `distill-*-batch.py` that auto-marks distilled without answer-packets
- Promoting from packet key_lines / theme labels without toolchain proof
- Skipping check-work report for a closed batch
