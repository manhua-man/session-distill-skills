# Session Distill Skills

将 Claude Code / Codex / Cursor / Grok 的 AI 会话记录蒸馏为结构化知识，支持跨平台。

## 架构图

```mermaid
flowchart TD
    subgraph SRC["输入：AI 客户端原始会话 (.jsonl)"]
        S1[Claude Code<br/>~/.claude/projects/*.jsonl]
        S2[Codex<br/>~/.codex/archived_sessions/*.jsonl]
        S3[Cursor<br/>~/.cursor/.../sessions]
        S4[Grok<br/>~/.grok/sessions/.../chat_history.jsonl]
    end

    subgraph DISTILL["蒸馏主链"]
        D1[session-distill]
        D2[codex-session-distill]
        D3[cursor-session-distill]
        D4[grok-session-distill]
    end

    PKT[packet<br/>含 Packet Audit]
    NOTE[session note<br/>distilled/sessions/]
    KB[knowledge-base.md<br/>稳定知识]

    subgraph EXPORT["导出 + 审批"]
        E1[packet-memory-export]
        REVIEW{review<br/>approve / reject / defer}
    end

    subgraph HELPERS["可选协作者 (review-stage)"]
        direction LR
        H1[grill-me<br/>对抗性压力测试]
        H2[answer-me<br/>证据补充]
        H3[ask-me<br/>架构咨询]
    end

    MEM[(claude-mem<br/>持久化记忆)]
    MD[mem-distill<br/>去重 / 归并 / 提炼]

    S1 --> D1
    S2 --> D2
    S3 --> D3
    S4 --> D4

    D1 & D2 & D3 & D4 --> PKT
    PKT --> NOTE
    NOTE --> KB

    PKT --> E1
    E1 --> REVIEW
    REVIEW -.可选.-> H1
    REVIEW -.可选.-> H2
    REVIEW -.可选.-> H3
    H1 & H2 & H3 -.决策支持.-> REVIEW
    REVIEW -->|approved| MEM
    MEM -.可选.-> MD
    MD --> KB

    classDef src fill:#e3f2fd,stroke:#1976d2
    classDef main fill:#fff9c4,stroke:#f57f17
    classDef helper fill:#f3e5f5,stroke:#7b1fa2,stroke-dasharray: 5 5
    classDef store fill:#c8e6c9,stroke:#2e7d32
    class S1,S2,S3,S4 src
    class D1,D2,D3,D4,E1 main
    class H1,H2,H3,MD helper
    class PKT,NOTE,KB,MEM store
```

**设计要点**：主链单向流动；协作者虚线连接，不写记忆、不阻塞主链；只有 approved 的条目才进入 claude-mem。

## 技能列表

### 蒸馏主链

| 技能 | 平台 | 说明 |
|------|------|------|
| `session-distill` | Claude Code | 核心蒸馏引擎：index -> bundle -> packet -> session note -> knowledge base |
| `codex-session-distill` | Codex | Codex 归档会话蒸馏 |
| `cursor-session-distill` | Cursor | Cursor 会话蒸馏 |
| `grok-session-distill` | Grok CLI | Grok `chat_history.jsonl` 会话蒸馏 |
| `packet-memory-export` | Claude Code | 从 packet 导出结构化 memory draft，支持 approve / reject / defer |

### 可选协作者

均 **可选**，缺失时不应阻塞主链。不写记忆、不批准条目、不替代 review 决策。

| 技能 | 用途 | 输出 |
|------|------|------|
| `mem-distill` | claude-mem 记忆去重/归并/提炼 | 稳定知识 -> knowledge-base.md |
| `grill-me` | 对抗性压力测试：候选结论是否过度概括 | keep / narrow / defer / reject + 失败模式 |
| `answer-me` | 证据补充：draft 缺代码/文档/测试证据时 | 证据来源 + 支持标签 |
| `ask-me` | 架构/路线图咨询：draft 触及更大设计决策时 | 推荐方案 + 权衡 + 风险 |

## 安装

```bash
# Claude Code
cp -r session-distill ~/.claude/skills/manhua/
cp -r packet-memory-export ~/.claude/skills/manhua/
cp -r mem-distill ~/.claude/skills/manhua/
cp -r grill-me ~/.claude/skills/manhua/
cp -r answer-me ~/.claude/skills/manhua/
cp -r ask-me ~/.claude/skills/manhua/

# Codex
cp -r codex-session-distill ~/.codex/skills/manhua/session-distill/

# Cursor
cp -r cursor-session-distill ~/.cursor/skills/session-distill/

# Grok CLI
cp -r grok-session-distill ~/.grok/skills/session-distill/
```

## 目录结构

```
session-distill-skills/
├── session-distill/              # Claude Code 核心蒸馏
│   ├── SKILL.md
│   ├── bin/session-distill.py
│   ├── references/
│   └── tests/
├── codex-session-distill/        # Codex 归档会话蒸馏
│   ├── SKILL.md
│   ├── bin/session-distill.py
│   ├── references/
│   └── tests/
├── cursor-session-distill/       # Cursor 会话蒸馏
│   └── bin/cursor-session-distill.py
├── grok-session-distill/         # Grok CLI 会话蒸馏
│   ├── SKILL.md
│   ├── bin/grok-session-distill.py
│   ├── references/
│   └── tests/
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