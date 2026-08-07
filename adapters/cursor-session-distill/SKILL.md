---
name: session-distill
description: |
  Cursor Composer 会话 Deep Distill：packet → answer-me 验证 → session note → KB。
  处理范式与 Grok 一致；禁止无验证的批量晋升。
argument-hint: "[index | run --next N | deep-distill --project <p>]"
---

# Cursor Session Distiller (Deep Distill)

Reads Cursor SQLite + JSONL agent transcripts. **Default paradigm: Grok Deep Distill** (3 sessions/batch).

**单一真源：** 本目录 `~/.cursor/skills/session-distill/` 是 Cursor 蒸馏工具的唯一安装位置。Claude Code / Codex 需要跑 Cursor 蒸馏时，也用这里的 `bin/` 脚本，不要维护 `~/.claude/skills/manhua/cursor-session-distill/` 副本。

**开始蒸馏前：** 先过 [tooling-gate.md](./references/tooling-gate.md)（`sync-distill-installs.py` + 测试全绿）。工具没就绪不跑批量蒸馏。

## Workspace

- Input: `~/.cursor/projects/<project>/agent-transcripts/<id>/<id>.jsonl`（或 sqlite composer 数据）
- Workdir: `~/.cursor/session-distill/` (`CURSOR_DISTILL_DIR`)
- Repo KB: `E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md`

## Default Workflow (无状态)

```powershell
$env:CURSOR_DISTILL_DIR = "$env:USERPROFILE\.cursor\session-distill"

# 1. (可选) 重建 manifest：扫描 sqlite 当前会话
python .cursor/skills/session-distill/bin/cursor-session-distill.py index

# 2. 无状态选批：--project 指定项目；packet 已存在即视为已处理并跳过（不维护进度状态）
python .cursor/skills/session-distill/bin/deep-distill-run.py --project servers --offset 0 --batch-size 3

# 3. AI: answer-me verify each Q (Grep/Read/git/Shell) → fill answer-packet Results

# 4. Write session note + promote ANSWERED only → session-knowledge-base.md

# 5. check-work report；本批产物（packets/answer-packets）即去重标记，保留不删
```

无状态约定：**不写队列进度文件、不做 mark distilled、不在 KB 记批次进度**。
已处理的会话靠 `packets/cursor-<id>.md` 存在性去重；清理旧产物用 `cleanup-cursor-distill.py`。

## References (load before distilling)

- `references/deep-distill-workflow.md` — canonical pipeline
- `references/distillation-rules.md` — promotion gates
- `references/output-layout.md` — paths and statuses

## Anti-patterns

- Do **not** use bulk auto-promote scripts without answer-packets.
- Do **not** promote from packet text alone when `Coverage: partial`.
- Chat history is hypotheses until toolchain verification.

## Low-level CLI

```powershell
python .cursor/skills/session-distill/bin/cursor-session-distill.py status
python .cursor/skills/session-distill/bin/cursor-session-distill.py run --next 1
python ~/.cursor/skills/session-distill/bin/cleanup-cursor-distill.py all --project servers --keep <id>
```
