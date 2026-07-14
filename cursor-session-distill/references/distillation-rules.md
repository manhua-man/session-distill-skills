# Distillation Rules

Promote only stable, reusable knowledge.

Keep in the session note:

- one-off paths, process IDs, timestamps, branch names, and temporary failures;
- task-local decisions that do not change future behavior;
- raw command noise after the useful command pattern has been captured.

Promote to `knowledge-base.md`:

- repeatable workflows;
- hidden file maps and debugging entrypoints;
- failure patterns that shorten future investigations;
- repo-specific rules that are not already clear in `AGENTS.md`, `CLAUDE.md`,
  `.kiro/steering`, docs, tests, or code.

When `Packet Audit` says `partial`, first inspect the raw `chat_history.jsonl`
around the relevant turn. The packet is an entrypoint, not the sole source of truth.

**Chat history is not evidence.** Session text may be wrong, incomplete, or stale.
Never promote directly from a packet or assistant reply.

### Mandatory gate: toolchain verification before promotion

For each candidate fact extracted from a session:

1. State the claim in one sentence (from raw JSONL, not from memory).
2. Verify with at least one **current** toolchain check:
   - `Read` / `Grep` on repo code, `AGENTS.md`, `CLAUDE.md`, steering, `docs/`
   - `git log` / `git show` for shipped commits
   - `Shell` for runtime truth (versions, paths, health) when the claim is environmental
3. Record result: `verified` | `stale` | `reject` with command/path evidence.
4. **Promote only `verified` rows.** `stale`/`reject` stay in the session note only.

Promotion order after verification: session note → `knowledge-base.md` → `docs/` →
steering → `AGENTS.md` / `CLAUDE.md` (only if not already canonical elsewhere).

If nothing passes verification, write `No Promotion` explicitly.