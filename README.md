# Session Distill Skills

将 Claude Code / Codex / Cursor 的 AI 会话记录蒸馏为结构化知识，支持跨平台。

## 技能列表

### 主链 skill

| 技能 | 平台 | 说明 |
|------|------|------|
| `session-distill` | Claude Code | 核心蒸馏引擎：index -> bundle -> packet -> session note -> knowledge base |
| `codex-session-distill` | Codex | Codex 原生适配版，处理 `rollout-*.jsonl` 归档会话 |
| `cursor-distill` | Cursor | Cursor 会话蒸馏脚本 |
| `packet-memory-export` | Claude Code | 从 packet 导出结构化 memory draft，支持审批流程 |
| `mem-distill` | Claude Code | 记忆蒸馏辅助，从 claude-mem 中提取和整理记忆 |

### 审查阶段可选协作者（review-stage collaborators）

这三个 skill 是 **可选的**，不在默认蒸馏主链上，缺失时不应阻塞主链。

| 技能 | 用途 | 输出 |
|------|------|------|
| `grill-me` | adversarial 压力测试：候选结论是否过度概括 | keep / narrow / defer / reject + 失败模式 |
| `answer-me` | 补充证据：候选 draft 缺代码/文档/测试证据时 | 证据来源 + 支持的标签 (new/refine/confirm/conflict/ephemeral) |
| `ask-me` | 架构/路线图咨询：draft 触及更大的设计决策时 | 推荐方案 + 权衡 + 风险 + 依赖 |

**重要边界**：这三者都 **不写记忆、不批准条目、不替代 review 决策**。它们只为 reviewer 提供决策支持。

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
