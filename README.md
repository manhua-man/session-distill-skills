# Session Distill Skills

Distill raw AI session transcripts (Claude Code, Codex, Cursor, Grok, Hermes, Antigravity, OpenCode) into structured, verifiable repository knowledge.

[中文文档 (Chinese Documentation)](README_zh.md)

## Architecture

```mermaid
flowchart TD
    subgraph SRC["Input: AI Client Transcripts (.jsonl / DB)"]
        S1["Claude Code / Codex<br/>~/.claude / ~/.codex"]
        S2["Cursor / Grok<br/>~/.cursor / ~/.grok"]
        S3["Antigravity agy<br/>~/.gemini/antigravity"]
        S4["Hermes / OpenCode"]
    end

    subgraph DISTILL["Distillation Pipeline (deep-distill-run.py)"]
        D1["claude-session-distill / codex-session-distill"]
        D2["cursor-session-distill / grok-session-distill"]
        D3["antigravity-session-distill"]
        D4["hermes / opencode-session-distill"]
    end

    PKT["Lossless Packet<br/>packets/session-id"]
    APKT["Answer Packet<br/>answer-packets/session-id"]
    NOTE["Session Note<br/>distilled/sessions/session-id"]

    subgraph HELPERS["Toolchain Verification & Review Helpers"]
        direction LR
        H1["answer-me<br/>Code Evidence Gathering"]
        H2["grill-me<br/>Adversarial Stress Test"]
        H3["grill-me-docs<br/>Doc-Code Consistency Audit"]
        H4["ask-me<br/>Architecture & Tradeoffs"]
    end

    KB["session-knowledge-base.md<br/>Single Source of Truth"]
    DOCS["docs/ Specifications & Reference"]

    S1 --> D1
    S2 --> D2
    S3 --> D3
    S4 --> D4

    D1 & D2 & D3 & D4 --> PKT
    PKT --> APKT
    APKT -.Toolchain Evidence.-> H1
    H1 -.Adversarial Audit.-> H2
    H1 -.Doc Inspection.-> H3
    H1 -.Tradeoff Consultation.-> H4
    H1 & H2 & H3 & H4 -->|ANSWERED| NOTE
    NOTE -->|Promote Stable Facts| KB
    NOTE -.Sync Specs.-> DOCS
```

## Core Distillation Paradigm (Deep Distill)

All 7 supported platforms execute identical post-processing rules via `shared/deep_distill_lib.py`:

1. **Batching**: Process 3 sessions per batch (`deep-distill-run.py --batch-size 3`).
2. **Compact Manifest Ingest**: Bounded exchange manifest (≤3000 Tokens) generated for fast exchange lookup.
3. **Answer Packet Gate**: Hypotheses -> Question Table -> Toolchain Verification -> Only `ANSWERED` rows promote to KB.
4. **Temporal Staleness Audit**: Verify claims against the current codebase HEAD; mark outdated facts `STALE` or `CONTRADICTED`.
5. **Check-work Report**: Audit report generated at `distilled/check-work/batch-*-report.md` before raw session purge.

## Supported Adapters

| Adapter | Platform | Source Format |
|---|---|---|
| `claude-session-distill` | Claude Code | `.jsonl` |
| `codex-session-distill` | Codex | Archived DB / JSONL |
| `cursor-session-distill` | Cursor | SQLite + JSONL |
| `grok-session-distill` | Grok CLI | `chat_history.jsonl` |
| `hermes-session-distill` | Hermes | SQLite `state.db` |
| `antigravity-session-distill` | Antigravity (agy) | `history.jsonl` + brain transcripts |
| `opencode-session-distill` | OpenCode | `storage/session` JSON tree |

## Installation

PowerShell One-Click Installer:

```powershell
.\shared\install.ps1 -Platforms cursor,grok,hermes,antigravity
```

## License & Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for testing guidelines and pull request checks.
