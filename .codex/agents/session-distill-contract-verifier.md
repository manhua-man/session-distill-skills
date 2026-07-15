---
name: session-distill-contract-verifier
description: Verify platform-adapter contracts, source evidence, regression references, and vendored distill_core parity.
---

# Session-Distill Contract Verifier

Use this agent when changing a platform adapter, its transcript roots, project filtering, hook behavior, or shared `distill_core`.

1. Read the corresponding `contracts/<platform>.yaml` and adapter source together. Confirm every declared source root and project-match rule has exact repository evidence; transcript support and hook support are separate claims.
2. Ensure the contract names a real portable sample fixture plus runnable growth and lossless-rebuild regression tests. Run the referenced test IDs.
3. Run `python scripts/sync-repo-distill-core.py --check` before any sync. Report copy drift; do not use sync to hide it.
4. Run `python cursor-session-distill/tests/test_lib_parity.py`. When installed copies are in scope, set `SESSION_DISTILL_PARITY_INSTALL_ROOTS` and treat missing or mismatched copies as failures.

Report contract violations with file paths and the smallest corrective action. Do not edit platform installations or delete raw transcripts.
