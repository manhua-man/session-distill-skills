# Distillation Rules

Promote only stable, reusable knowledge verified against current repo/runtime into the target project's canonical knowledge base (`session-knowledge-base.md`).

## What to keep vs what to promote

### Keep in the session note:
- One-off paths, process IDs, timestamps, branch names, and temporary execution failures;
- Task-local decisions that do not change future behavior;
- Raw command noise after the useful command pattern has been captured.

### Promote to `session-knowledge-base.md`:
- Repeatable workflows and verification procedures;
- Hidden file maps, configuration entrypoints, and debugging setups;
- Failure patterns that shorten future investigations;
- Repo-specific rules not already canonical in `AGENTS.md`, `CLAUDE.md`, steering, docs, tests, or code.

---

## Deep Distill promotion gate (Mandatory)

Chat history and packet text are **hypotheses**, not evidence. Session text may be wrong, incomplete, or stale. **Never promote directly from a packet or assistant reply.**

Before any KB / docs / AGENTS edit:

1. **Claim Extraction**: State each candidate fact in one sentence from raw transcripts.
2. **Current Toolchain Verification**: Verify each claim with current repo/runtime checks:
   - `Read` / `Grep` on current repo code, `AGENTS.md`, `CLAUDE.md`, steering, `docs/`
   - `git log` / `git show` for shipped commits
   - `Shell` for runtime truth (versions, paths, port health) when environmental
3. **Temporal Staleness Audit (时效性与历史时间差审计)**: Historical sessions are hypotheses. **Current repo HEAD is sole truth.** If code has been refactored or superseded, mark as `STALE` / `CONTRADICTED` and refuse promotion!
4. **Record Verification Result**: `verified` | `stale` | `reject` with command/path evidence.
5. **Promote Only `verified` Rows**: Only `verified` / `ANSWERED` rows may promote.
6. **Dynamic Topic Classification**: Categorize promoted entries by **Functional Domain / Topic** based on the target project's actual module architecture (e.g. Deploy, Auth, Payment, Core Business Modules), rather than creating platform-specific or batch-specific headers.
7. **Freshness Timestamp Formatting**: Format promoted entries with verification date: `- **标题**: 验证后的稳定知识结论 (verified YYYY-MM-DD).` Do **not** append raw conversation `Source ID` tags.
8. Complete `distilled/check-work/batch-*-report.md`.

If nothing passes verification, write `No Promotion` explicitly.