# Session Distill Skills

将 Claude Code / Codex / Cursor 的 AI 会话记录蒸馏为结构化知识，支持跨平台。

## 技能列表

### 主链 skill

| 技能 | 平台 | 说明 |
|------|------|------|
| `session-distill` | Claude Code | 核心蒸馏引擎：index -> bundle -> packet -> session note -> knowledge base |
| `codex-session-distill` | Codex | Codex 归档会话蒸馏 |
| `cursor-distill` | Cursor | Cursor 会话蒸馏 |

### 导出 + 审批 skill

| 技能 | 说明 |
|------|------|
| `packet-memory-export` | 从 packet 导出结构化 memory draft，支持 approve / reject / defer |

### 可选协作者（review-stage collaborators）

以下 skill 均 **可选**，不在默认蒸馏主链上，缺失时不应阻塞主链。都不写记忆、不批准条目、不替代 review 决策。

| 技能 | 用途 | 输出 |
|------|------|------|
| `mem-distill` | claude-mem 记忆去重/归并/提炼 | 稳定知识 -> knowledge-base.md |
| `grill-me` | 对抗性压力测试：候选结论是否过度概括 | keep / narrow / defer / reject + 失败模式 |
| `answer-me` | 证据补充：候选 draft 缺代码/文档/测试证据时 | 证据来源 + 支持的标签 (new/refine/confirm/conflict/ephemeral) |
| `ask-me` | 架构/路线图咨询：draft 触及更大的设计决策时 | 推荐方案 + 权衡 + 风险 + 依赖 |

## 架构图

```mermaid
flowchart TD
    subgraph SRC["输入：AI 客户端原始会话 (.jsonl)"]
        S1[Claude Code<br/>~/.claude/projects/*.jsonl]
        S2[Codex<br/>~/.codex/archived_sessions/*.jsonl]
        S3[Cursor<br/>~/.cursor/.../sessions]
    end

    subgraph DISTILL["主链：蒸馏 (Distillation)"]
        D1[session-distill]
        D2[codex-session-distill]
        D3[cursor-distill]
    end

    PKT[packet<br/>含 Packet Audit]
    NOTE[session note<br/>distilled/sessions/]
    KB[knowledge-base.md<br/>稳定知识]

    subgraph EXPORT["主链：导出 + 审批 (Memory Pipeline)"]
        E1[packet-memory-export]
        REVIEW{review<br/>approve / reject / defer}
        E2[mem-distill<br/>去重 / 归并 / 提炼]
    end

    subgraph HELPERS["可选协作者 (Review-stage Collaborators)"]
        direction LR
        H1[grill-me<br/>对抗性压力测试]
        H2[answer-me<br/>证据补充]
        H3[ask-me<br/>架构咨询]
    end

    MEM[(claude-mem<br/>持久化记忆)]

    S1 --> D1
    S2 --> D2
    S3 --> D3

    D1 & D2 & D3 --> PKT
    PKT --> NOTE
    NOTE --> KB

    PKT --> E1
    E1 --> REVIEW
    REVIEW -.可选询问.-> H1
    REVIEW -.可选询问.-> H2
    REVIEW -.可选询问.-> H3
    H1 & H2 & H3 -.返回决策支持.-> REVIEW
    REVIEW -->|approved| MEM
    MEM --> E2
    E2 --> KB

    classDef src fill:#e3f2fd,stroke:#1976d2
    classDef main fill:#fff9c4,stroke:#f57f17
    classDef helper fill:#f3e5f5,stroke:#7b1fa2,stroke-dasharray: 5 5
    classDef store fill:#c8e6c9,stroke:#2e7d32
    class S1,S2,S3 src
    class D1,D2,D3,E1,E2 main
    class H1,H2,H3 helper
    class PKT,NOTE,KB,MEM store
```

### 设计要点

1. **三平台共用一套蒸馏模型**：原始 jsonl -> packet -> session note -> knowledge base
2. **主链单向流动**：不要在主链上做条件分支
3. **协作者虚线连接**：grill-me / answer-me / ask-me 只在 review 阶段被询问，不写记忆、不阻塞主链
4. **审批门控**：只有 approved 的条目才进入 claude-mem，避免污染长期记忆

## 工作流

```
原始会话 JSONL
    │
    ▼
session-distill run --next N     ← 生成 packet
    │
    ▼
AI 读取 packet + 写 session note  ← 蒸馏
    │
    ▼
packet-memory-export export       ← 导出 memory draft (可选)
    │
    ▼
审批 / 同步到 claude-mem          ← mem-distill (可选)
```

## 安装

```bash
# Claude Code
cp -r session-distill ~/.claude/skills/manhua/
cp -r packet-memory-export ~/.claude/skills/manhua/
cp -r mem-distill ~/.claude/skills/manhua/

# Codex
cp -r codex-session-distill ~/.codex/skills/manhua/session-distill/

# Cursor
cp -r cursor-distill ~/.cursor/skills/session-distill/
```

## 目录结构

```
session-distill-skills/
├── session-distill/          # Claude Code 核心蒸馏
│   ├── SKILL.md
│   ├── bin/session-distill.py
│   ├── references/
│   └── tests/
├── codex-session-distill/    # Codex 原生适配
│   ├── SKILL.md
│   ├── bin/session-distill.py
│   ├── references/
│   └── tests/
├── packet-memory-export/     # Memory draft 导出
│   ├── SKILL.md
│   ├── bin/packet-memory-export.py
│   └── tests/
├── mem-distill/              # 记忆蒸馏辅助
│   └── SKILL.md
├── cursor-distill/           # Cursor 蒸馏
│   └── bin/cursor-distill.py
├── grill-me/                 # 审查协作者：对抗性压力测试
│   └── SKILL.md
├── answer-me/                # 审查协作者：证据补充
│   └── SKILL.md
└── ask-me/                   # 审查协作者：架构咨询
    └── SKILL.md
```
