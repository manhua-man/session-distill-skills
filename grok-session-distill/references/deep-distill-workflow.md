# Servers Deep Distill Workflow

Scope: `E:\project\servers` Grok sessions only. Parallelism: **3 sessions per batch**.

## Principles

1. **Chat is hypotheses** — raw `chat_history.jsonl` and packets are claim sources, not evidence.
2. **Toolchain before promotion** — every claim gets an `answer-me` verification row before any file write outside session notes.
3. **Code > docs > chat** — on conflict, current repo wins; session marked `stale` or `CONTRADICTED`.

## Pipeline (per batch)

```
Phase 0  Queue     servers-deep-queue.md picks next 3 session IDs (chronological)
Phase 1  Ingest    grok-session-distill bundle --force (refresh packet index)
Phase 2  Extract   Per session: user turns + assistant final answer → claim list (1 sentence each)
Phase 3  Verify    answer-me protocol (see below) → answer-packet per session
Phase 4  Promote   ONLY rows with Status=ANSWERED and Lens=repo/runtime
Phase 5  check-work  Subagent verifies promotions (diff + evidence replay); FAIL → fix or demote
Phase 6  Record    session note + optional KB/docs/AGENTS/steering updates
Phase 7  Close     mark distilled; update queue progress
```

## Phase 3: answer-me verification (mandatory)

For each claim, add a question row:

| Field | Content |
|-------|---------|
| ID | Q1, Q2, … |
| Lens | `ai-entry` / `deploy` / `payment` / `runtime` / `session-local` |
| Class | DISCOVERABLE / EXTERNAL_FACT / HUMAN_DECISION |

**Toolchain (use what fits the lens):**

| Tool | When |
|------|------|
| `Grep` / `Read` / `Glob` | Repo files, AGENTS, CLAUDE, steering, docs |
| `Shell` + `git log/show` | Shipped commits, file history |
| `Shell` + runtime | `pwsh`, `docker ps`, `Test-Path` (environment claims) |
| `CallMcpTool` mcp-search | Claim references past decision — `search` → `timeline` → `get_observations`, then re-`Read` code |
| `CallMcpTool` harness-mem `prepare_session_distill` | Optional cross-client context (not a substitute for repo grep) |
| `CallMcpTool` readonly-runtime | Production/test health when claim is operational |
| **check-work** (`Task` subagent) | After promotion edits: replay evidence, `git diff`, reject stale promotions |
| **Not used for verify** | Packet text alone, assistant memory, batch theme labels |

**Status assignment (answer-me):**

- `ANSWERED` → eligible for promotion
- `PARTIAL` / `UNANSWERED` / `CONTRADICTED` / `NOT_APPLICABLE` → session note only

## Phase 4: promotion routing

| Destination | Gate |
|-------------|------|
| `distilled/sessions/<id>.md` | Always (includes full answer-packet) |
| `distilled/answer-packets/<id>.md` | Always (machine-readable verify log) |
| `session-knowledge-base.md` (repo §I) | ANSWERED + cross-session stable |
| `docs/` | ANSWERED + human-facing; no duplicate of existing canonical doc |
| `.kiro/steering/` | ANSWERED + scoped override |
| `AGENTS.md` / `CLAUDE.md` | ANSWERED + missing from current entry docs |

## Artifacts

```
~/.grok/session-distill/
  servers-deep-queue.md
  distilled/
    answer-packets/<session-id>.md   # answer-me output
    sessions/<session-id>.md         # summary + promotion decision
  E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md
```

## Runner

```powershell
python $env:USERPROFILE\.grok\skills\session-distill\bin\deep-distill-run.py --batch-size 3 --project servers
```

Manual mode: run phases 2–5 in Cursor with this doc + `distillation-rules.md` + `answer-me` skill loaded.