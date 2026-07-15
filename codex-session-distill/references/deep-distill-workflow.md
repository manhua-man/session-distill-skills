# Deep Distill Workflow (Codex / servers)

Canonical processing for **Codex** archived rollouts under `~/.codex/archived_sessions/`.

## Pipeline (per batch of 3)

```
Phase 0  Queue      ~/.codex/session-distill/servers-deep-queue.md
Phase 1  Ingest     deep-distill-run.py --offset N --batch-size 3 (reindex + bundle)
Phase 2  Extract    answer-packets/<session-id>.md with claims + PENDING Q rows
Phase 3  Verify     answer-me: Grep/Read/git/Shell on E:/project/servers
Phase 4  Promote    ONLY Status=ANSWERED → session-knowledge-base.md §Codex Deep Distill
Phase 5  check-work distilled/check-work/batch-offset-N-report.md
Phase 6  Record     distilled/sessions/<session-id>.md
Phase 7  Close      session-distill.py mark <id> distilled (retains raw JSONL)
```

## Scope filter

Only sessions whose JSONL `cwd` contains `servers` (excludes `servers-wt-*` worktrees).

## Commands

```powershell
python $env:USERPROFILE\.codex\skills\manhua\session-distill\bin\deep-distill-run.py --offset 0 --batch-size 3
python $env:USERPROFILE\.codex\skills\manhua\session-distill\bin\session-distill.py status
python $env:USERPROFILE\.codex\skills\manhua\session-distill\bin\session-distill.py mark <session-id> distilled
```

## KB target

`E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md` — **not** `~/.codex/session-distill/knowledge-base.md` (redirect only).

## Anti-patterns

- Bulk auto-promote without answer-packet verification
- Promote Unity/code/MCP-only sessions into servers KB
- Skip check-work before `mark distilled`
