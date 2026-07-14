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

When `Packet Audit` says `partial`, first inspect the raw JSONL around the
relevant turn. The packet is an entrypoint, not the sole source of truth.

If nothing should be promoted, write that explicitly in the session note with a
`No Promotion` or `Promotion Decision` section.
