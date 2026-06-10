# Session Distill Skills

将 Claude Code / Codex / Cursor 的 AI 会话记录蒸馏为结构化知识，支持跨平台。

## 技能列表

| 技能 | 平台 | 说明 |
|------|------|------|
| `session-distill` | Claude Code | 核心蒸馏引擎：index -> bundle -> packet -> session note -> knowledge base |
| `codex-session-distill` | Codex | Codex 原生适配版，处理 `rollout-*.jsonl` 归档会话 |
| `cursor-distill` | Cursor | Cursor 会话蒸馏脚本 |
| `packet-memory-export` | Claude Code | 从 packet 导出结构化 memory draft，支持审批流程 |
| `mem-distill` | Claude Code | 记忆蒸馏辅助，从 claude-mem 中提取和整理记忆 |

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
└── cursor-distill/           # Cursor 蒸馏
    └── bin/cursor-distill.py
```
