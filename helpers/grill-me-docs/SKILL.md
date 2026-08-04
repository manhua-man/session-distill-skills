---
name: grill-me-docs
version: 0.1.0
description: |
  Automated documentation vs code consistency pressure tester (Agent-to-Doc Auditor).
  Use to audit markdown documentation in `docs/` against actual codebase entities, DTOs, controllers, and services.
allowed-tools:
  - Read
  - Grep
  - Glob

---

# Grill Me Docs (Doc-vs-Code Consistency Auditor)

## Role

`grill-me-docs` is an automated collaborator for auditing human and architecture documentation in `docs/` against actual codebase implementation.

It applies toolchain verification (`Read`, `Grep`, `Glob`) to pressure-test documentation statements, detecting outdated specs, code contradictions, and missing documentation.

## Audit Boundary

The documentation pressure testing workflow operates directly on repository files:

```text
docs/*.md -> grill-me-docs -> toolchain cross-reference (entities, DTOs, controllers) -> verification note
```

`grill-me-docs` does not alter production code directly; it outputs precise doc-vs-code audit reports with file and line evidence.

## When To Use

- Auditing existing specifications under `docs/` for accuracy after code refactoring.
- Verifying client/server API integration docs (`docs/03-功能模块/` / `docs/04-开发指南/`) against NestJS controllers and DTOs.
- Checking for stale environment variables, endpoint paths, or SQL table names cited in markdown guides.
- Reviewing documentation pull requests before landing.

## Verification Verdicts

For each audited document section or claim, return one of the following verdicts:

- `ACCURATE`: Document statements match current code implementation 100%.
- `STALE`: Document cites outdated endpoint paths, table columns, default values, or environment keys that have been renamed or refactored.
- `CONTRADICTED`: Document describes a business logic or security behavior that directly conflicts with live code behavior.
- `MISSING_SPECS`: Source code contains important boundary conditions or feature rules omitted from the document.

## Expected Output Format

Return a structured Audit Report containing:

```markdown
# Doc Audit Report: [document path]

## Summary
- Target Document: `docs/path/to/spec.md`
- Codebase Scope: `packages/nestjs-server/src/...`
- Verdict: PASS / REVISION_REQUIRED

## Audit Findings

### 1. [Finding Title]
- **Verdict**: `STALE` | `CONTRADICTED` | `ACCURATE` | `MISSING_SPECS`
- **Doc Statement**: "`...`" (line XX)
- **Code Evidence**: [filename](file:///path/to/file#L10-L25)
- **Recommended Revision**: Precise text edit to align `spec.md` with code truth.
```

## Non-Goals

- Do not alter production TS/SQL code.
- Do not make assumptions without reading actual source code files.
- Do not approve contradictory documentation without code evidence.
