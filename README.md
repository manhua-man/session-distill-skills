# Session Distill Skills

将 Claude Code / Codex / Cursor / Grok 的 AI 会话记录蒸馏为结构化知识，支持跨平台。

## 架构图

```mermaid
flowchart TD
    subgraph SRC["输入：AI 客户端原始会话 (.jsonl / DB)"]
        S1[Claude Code / Codex<br/>~/.claude | ~/.codex]
        S2[Cursor / Grok<br/>~/.cursor | ~/.grok]
        S3[Antigravity agy<br/>~/.gemini/antigravity]
        S4[Hermes / OpenCode]
    end

    subgraph DISTILL["蒸馏主链 (deep-distill-run.py)"]
        D1[session-distill / codex-session-distill]
        D2[cursor-session-distill / grok-session-distill]
        D3[antigravity-session-distill]
        D4[hermes / opencode-session-distill]
    end

    PKT[Lossless Packet<br/>packets/<session-id>.md]
    APKT[Answer Packet<br/>answer-packets/<session-id>.md]
    NOTE[Session Note<br/>distilled/sessions/<session-id>.md]

    subgraph HELPERS["协作者工具链 (Review & Toolchain Verification)"]
        direction LR
        H1[answer-me<br/>代码实证搜集]
        H2[grill-me<br/>结论对抗性压力测试]
        H3[grill-me-docs<br/>文档代码一致性审计]
        H4[ask-me<br/>架构与折衷咨询]
    end

    KB[session-knowledge-base.md<br/>项目单一真源 (按功能领域归集)]
    DOCS[docs/ 人类规格与 AI 说明]

    S1 --> D1
    S2 --> D2
    S3 --> D3
    S4 --> D4

    D1 & D2 & D3 & D4 --> PKT
    PKT --> APKT
    APKT -.Toolchain 实证.-> H1
    H1 -.对抗质询.-> H2
    H1 -.文档比对.-> H3
    H1 -.折衷参考.-> H4
    H1 & H2 & H3 & H4 -->|ANSWERED| NOTE
    NOTE -->|晋升稳定知识| KB
    NOTE -.同步修正.-> DOCS

    classDef src fill:#e3f2fd,stroke:#1976d2
    classDef main fill:#fff9c4,stroke:#f57f17
    classDef helper fill:#f3e5f5,stroke:#7b1fa2,stroke-dasharray: 5 5
    classDef store fill:#c8e6c9,stroke:#2e7d32
    class S1,S2,S3,S4 src
    class D1,D2,D3,D4 main
    class H1,H2,H3,H4 helper
    class PKT,APKT,NOTE,KB,DOCS store
```

**设计要点**：主链单向流动；协作者工具虚线连接，不盲信 Prompt 假设、不阻塞主链；所有提炼出的结论经过工具链 (`answer-me`) 代码实证与对抗质询 (`grill-me`, `grill-me-docs`) 后，直接晋升至项目的单一真源 `session-knowledge-base.md`（按项目功能领域归集）及相关文档。

## Deep Distill 范式（全平台统一）

所有平台的**后处理**均遵循 Grok Deep Distill（见 `shared/references/deep-distill-workflow.md`）：

1. **每批 3 条** — `deep-distill-run.py --batch-size 3`
2. **answer-packet** — 假设 → Q 表 → toolchain 验证 → 仅 `ANSWERED` 晋升
3. **check-work** — 每批 `distilled/check-work/batch-*-report.md`
4. **禁止** — 无 answer-me 的批量 `distill-*-batch.py` 自动晋升

| 平台 | Runner |
|------|--------|
| Grok | `grok-session-distill/bin/deep-distill-run.py` |
| Cursor | `cursor-session-distill/bin/deep-distill-run.py` |
| Codex | `codex-session-distill/bin/deep-distill-run.py` |
| Claude | `session-distill/bin/deep-distill-run.py` |
| Hermes | `hermes-session-distill/bin/deep-distill-run.py` |
| Antigravity | `antigravity-session-distill/bin/deep-distill-run.py` |
| OpenCode | `opencode-session-distill/bin/deep-distill-run.py` |

共享库：`shared/deep_distill_lib.py`（各平台 `bin/` 下有副本便于安装）。

## 技能列表

### 蒸馏主链

| 技能 | 平台 | 说明 |
|------|------|------|
| `session-distill` | Claude Code | Claude 会话 Deep Distill（`.jsonl`） |
| `codex-session-distill` | Codex | Codex 归档会话 Deep Distill |
| `cursor-session-distill` | Cursor | Cursor 会话 Deep Distill（SQLite + JSONL） |
| `grok-session-distill` | Grok CLI | Grok `chat_history.jsonl` Deep Distill |
| `hermes-session-distill` | Hermes | Hermes SQLite `state.db` Deep Distill |
| `antigravity-session-distill` | Antigravity (agy) | `history.jsonl` + brain transcripts |
| `opencode-session-distill` | OpenCode | `storage/session` JSON tree Deep Distill |
| `packet-memory-export` | Claude Code | 从 packet 导出结构化 memory draft，支持 approve / reject / defer |

## Adapter capability and verification matrix

`full` means the adapter has repository-local fixture coverage for transcript ingest; it does **not** mean every client release has been verified on a real host. Hook support is intentionally reported separately.

| Platform | Transcript | Growth requeue | Lossless rebuild | Hooks | Verification scope |
|---|---|---|---|---|---|
| Claude Code | full | yes | yes | no | repository fixture + contract |
| Codex | full | yes | yes | no | repository fixture + contract |
| Cursor | full | yes | yes | no | repository fixture + contract |
| Grok | full | yes | yes | no | repository fixture + contract |
| Hermes | full | yes | yes | no | repository fixture + contract |
| Antigravity | full | yes | yes | no | repository fixture + contract |
| OpenCode | full | yes | yes | no | repository fixture + contract |

Before claiming a platform is verified against a real client release, add a sanitized captured sample, the client version, verification date, and a regression test to its adapter contract. Until then, upstream transcript-format changes remain a manual compatibility check.

### 可选协作者

均 **可选**，缺失时不应阻塞主链。不写记忆、不批准条目、不替代 review 决策。

| 技能 | 用途 | 输出 |
|------|------|------|
| `mem-distill` | claude-mem 记忆去重/归并/提炼 | 稳定知识 -> knowledge-base.md |
| `grill-me` | 对抗性压力测试：候选结论是否过度概括 | keep / narrow / defer / reject + 失败模式 |
| `answer-me` | 证据补充：draft 缺代码/文档/测试证据时 | 证据来源 + 支持标签 |
| `ask-me` | 架构/路线图咨询：draft 触及更大设计决策时 | 推荐方案 + 权衡 + 风险 |

## 安装

一键安装（推荐）：

```powershell
cd e:\project\session-distill-skills-tmp
.\shared\install.ps1
# 或只装部分平台：
.\shared\install.ps1 -Platforms cursor,grok,hermes,antigravity
# 先预览将要写入的路径（不复制、不覆盖）：
.\shared\install.ps1 -Platforms codex -WhatIf
```

安装器会先把新版本复制到同目录的临时目录，再替换目标；被替换的技能和命令会保留在临时目录下的带时间戳备份中。可用 `-BackupRoot <path>` 指定备份位置。

手动安装：

```bash
cp -r session-distill ~/.claude/skills/manhua/
cp session-distill/commands/session-distill.md ~/.claude/commands/
cp -r packet-memory-export ~/.claude/skills/manhua/
cp -r mem-distill ~/.claude/skills/manhua/
cp -r grill-me ~/.claude/skills/manhua/
cp -r answer-me ~/.claude/skills/manhua/
cp -r ask-me ~/.claude/skills/manhua/

# Codex
cp -r codex-session-distill ~/.codex/skills/manhua/session-distill/
cp codex-session-distill/commands/session-distill.md ~/.codex/commands/  # if supported

# Cursor
cp -r cursor-session-distill ~/.cursor/skills/session-distill/
cp cursor-session-distill/commands/session-distill.md ~/.cursor/commands/

# Grok CLI
cp -r grok-session-distill ~/.grok/skills/session-distill/
cp grok-session-distill/commands/session-distill.md ~/.grok/commands/

# Hermes
cp -r hermes-session-distill %LOCALAPPDATA%/hermes/skills/session-distill/

# Antigravity
cp -r antigravity-session-distill ~/.gemini/antigravity-cli/skills/session-distill/

# OpenCode
cp -r opencode-session-distill ~/.config/opencode/skills/session-distill/

# Sync shared deep_distill_lib to all platform bins after edits
python shared/sync_deep_distill_lib.py
```

## 目录结构

```
session-distill-skills/
├── session-distill/              # Claude Code Deep Distill
│   ├── SKILL.md
│   ├── commands/session-distill.md
│   ├── bin/session-distill.py
│   ├── bin/deep-distill-run.py
│   ├── bin/deep_distill_lib.py
│   ├── references/
│   └── tests/
├── codex-session-distill/        # Codex Deep Distill
│   ├── SKILL.md
│   ├── commands/session-distill.md
│   ├── bin/session-distill.py
│   ├── bin/deep-distill-run.py
│   ├── bin/deep_distill_lib.py
│   ├── references/
│   └── tests/
├── shared/                       # 跨平台 Deep Distill 共享库与 workflow
│   ├── deep_distill_lib.py
│   ├── sync_deep_distill_lib.py
│   ├── install.ps1
│   └── references/deep-distill-workflow.md
├── cursor-session-distill/       # Cursor Deep Distill
│   ├── SKILL.md
│   ├── commands/session-distill.md
│   ├── bin/cursor-session-distill.py
│   ├── bin/deep-distill-run.py
│   ├── bin/deep_distill_lib.py
│   └── references/
├── grok-session-distill/         # Grok CLI Deep Distill
│   ├── SKILL.md
│   ├── commands/session-distill.md
│   ├── bin/grok-session-distill.py
│   ├── bin/deep-distill-run.py
│   ├── bin/deep_distill_lib.py
│   ├── references/
│   └── tests/
├── hermes-session-distill/       # Hermes SQLite Deep Distill
├── antigravity-session-distill/  # Antigravity agy Deep Distill
├── opencode-session-distill/     # OpenCode storage Deep Distill
├── packet-memory-export/         # Memory draft 导出 + 审批
│   ├── SKILL.md
│   ├── bin/packet-memory-export.py
│   └── tests/
├── mem-distill/                  # 可选：claude-mem 记忆整理
│   └── SKILL.md
├── grill-me/                     # 可选：对抗性压力测试
│   └── SKILL.md
├── answer-me/                    # 可选：证据补充
│   └── SKILL.md
└── ask-me/                       # 可选：架构咨询
    └── SKILL.md
```
