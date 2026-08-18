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

## 知识库路径防护规约

- **主真值知识库 (Canonical KB)**：`E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md`
- **本地 Redirect 壳文件**：`~/.cursor/session-distill/knowledge-base.md` 仅为重定向壳文件（~333B 属正常），**严禁向壳文件内写入任何知识内容**！

## Default Workflow (无状态) — 全链路闭环

**完成一批 = Phase 2/3/4/5 全部跑完**，缺一不可；禁止只跑 Phase 2 就宣布完成。

```powershell
$env:CURSOR_DISTILL_DIR = "$env:USERPROFILE\.cursor\session-distill"

# Phase 2  批量蒸馏：产出 packets + answer-packets（一一对应，无空产物）
python .cursor/skills/session-distill/bin/deep-distill-run.py --project servers --offset 0 --batch-size 3
#   完成标准：packets 数 = answer-packets 数，sid 一一对应，无空产物（文件非空、Results 表有行或注明零-claims）

# Phase 3  answer-me 验证：对每个 answer-packet 的 Q 逐条分类回填 Results 表
#   完成标准：全批 Q 行 100% 定态（ANSWERED/CONTRADICTED/UNANSWERED/NOT_APPLICABLE），PENDING=0
#   判定：可工具链验证的 repo 事实 → ANSWERED/CONTRADICTED；一次性运维/调查/开发指令 → UNANSWERED
#   蒸馏流程自身会话 → NOT_APPLICABLE；仅 chat 无工具链证据 → 不晋升

# Phase 4  晋升：仅 Status=ANSWERED 行写入 canonical KB
#   E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md
#   ~/.cursor/session-distill/knowledge-base.md 是 redirect 壳（333B 属正常），不要向壳内写内容
#   完成标准：KB 有本次新增条目，knowledge-review-state.json 已更新

# Phase 5  check-work 报告：写 distilled/check-work/batch-<project>-full-<N>-report.md
#   必须包含：All/Unanswered/NotApplicable/Contradicted/Answered 计数 + ANSWERED 表 + CONTRADICTED 证据表
```

> Phase 编号对应 `references/deep-distill-workflow.md` 的 Phase 2=Extract、3=Verify、4=Promote、5=check-work（本页 Phase 2 含其 Phase 0/1 的选批+ingest）。

无状态约定：**不写队列进度文件、不做 mark distilled、不在 KB 记批次进度**。
已处理的会话靠 `packets/cursor-<id>.md` 存在性去重；清理旧产物用 `cleanup-cursor-distill.py`。

## References (load before distilling)

- `references/deep-distill-workflow.md` — canonical pipeline
- `references/distillation-rules.md` — promotion gates
- `references/output-layout.md` — paths and statuses

## Cursor 存储模型与 UI 归档映射规约

- **UI 呈现行为**：Cursor 侧栏界面的 “Archived” 列表囊括了所有不在当前打开 Tabs 中的历史/归档会话。
- **底层 SQLite 结构 (`state.vscdb`)**：
  - 会话头全量保存在 `ItemTable` 的 `composer.composerHeaders` -> `allComposers` 中；
  - 时间戳字段标准键名为 `lastUpdatedAt`（毫秒数值，非 `lastUpdatedTime`）；
  - 工作区路径保存在嵌套对象 `workspaceIdentifier.uri.fsPath` 或 `path`；
  - 对话内容存储在 `cursorDiskKV` 的 `composerData:<id>` 与 `bubbleId:<id>:<bubble_id>`。

## Anti-patterns 常见误区防范

- **只跑 Phase 2 就收尾**：批量蒸馏产出 packets 不算完成，Phase 3/4/5 必须继续。
- **未经工具链校验即晋升**：Transcript 均为假设，未经 Grep/Read/git/Shell 实证禁止写入主 KB。
- **误写 Redirect 壳文件**：向本地 `knowledge-base.md` 重定向壳文件写内容，而非主 KB `session-knowledge-base.md`。
- **未分类平铺追加**：未归入对应 `## N. 模块` 或自建新领域模块，直接在文件末尾平铺堆叠散乱文本。
- **缺失终审门禁**：Session Note 缺少 `## Final Session Review` 或未通过 `validate_final_review()` 即标记 `distilled`。
- **普通 mark 时误删 Raw**：在 `mark distilled` 时硬删原始 JSONL 转录（必须使用 `prune-raw --confirm` 并保留审计日志）。
- **仅按 is_archived 字段硬过滤**：Cursor 侧栏 “Archived” 列表包含所有非活跃历史会话，但底层 `allComposers` 并不全部显式打 `isArchived: true`。严禁仅按 `is_archived == True` 做硬过滤，否则会导致 90%+ 历史会话漏网。


## Low-level CLI

```powershell
python .cursor/skills/session-distill/bin/cursor-session-distill.py status
python .cursor/skills/session-distill/bin/cursor-session-distill.py run --next 1
python ~/.cursor/skills/session-distill/bin/cleanup-cursor-distill.py all --project servers --keep <id>
```