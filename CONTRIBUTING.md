# Contributing

## Local checks

Run the complete repository suite before opening a pull request:

```powershell
python scripts\run-all-tests.py
```

The suite checks adapter contracts, repository-local fixtures, lossless revision
rebuilds, growth requeue behavior, promotion gates, and shared-core parity. It
does not prove compatibility with every installed client version; include a
sanitized real-client fixture when an upstream transcript format changes.

## Adapter changes

For every adapter update:

1. Keep its contract in `contracts/` accurate, including concrete source-root and project-match evidence.
2. Add or update fixture, growth, and lossless-rebuild regression coverage.
3. Run `python scripts/sync-repo-distill-core.py` after changing `shared/distill_core`.
4. Preserve raw transcripts by default. Any deletion must remain an explicit, confirmed, auditable operation.

Do not add credentials, private transcripts, or absolute local paths to fixtures or documentation.
