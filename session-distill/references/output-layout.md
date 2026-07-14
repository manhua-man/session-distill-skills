# Output Layout

> Synced from the repo-local session-distill shared template.
> Edit `scripts/ai/session-distill/templates/output-layout.template.md` and rerun `python scripts/ai/session-distill/sync_references.py` from the repo root.

Claude `session-distill` 的默认工作区：

`~/.claude/session-distill`

## 文件布局

| 路径 | 用途 |
|------|------|
| `manifest.json` | 已发现 session 及其状态的唯一真值源 |
| `servers-deep-queue.md` | Deep Distill 批次进度（每批 3 条） |
| `packets/<session-id>.md` | 从 Claude `.jsonl` 生成的 review packet |
| `distilled/answer-packets/<session-id>.md` | 假设 + answer-me Results 表（晋升门禁） |
| `distilled/sessions/<session-id>.md` | 验证后的 session note |
| `distilled/check-work/batch-*-report.md` | 每批晋升审计 |
| `knowledge-base.md` | 跨会话稳定知识（仅 ANSWERED） |
| `memory-drafts/<session-id>.json` | 可选：packet-memory-export 导出的 memory draft |

## 默认链路（Deep Distill）

`raw session → packet → answer-packet → answer-me 验证 → session note → knowledge-base（仅 ANSWERED）→ check-work → mark`

`packet → packet-memory-export → memory-drafts → claude-mem` 是增强链路，不是默认 promotion gate。

## 状态含义

- `new`
  - 已索引，尚未生成 packet
- `bundled`
  - packet 已生成，等待 Deep Distill（answer-packet）
- `distilled`
  - answer-packet 已验证、session note 已写、check-work PASS、晋升决策已记录
- `skipped`
  - 主动跳过，不参与当前队列

## 推荐循环（Deep Distill）

1. `deep-distill-run.py --offset <N> --batch-size 3`
2. answer-me 填 answer-packet Results 表
3. 仅 `ANSWERED` 写入 `knowledge-base.md`
4. 写 `distilled/sessions/<session-id>.md`
5. 完成 `distilled/check-work/batch-*-report.md`
6. `mark distilled` 或 `skipped`

## Enhanced Path

1. 如果你只做 standalone distill，packet 后面直接接 session note / knowledge-base。
2. 如果你要导出结构化记忆候选，运行 `packet-memory-export export --session <session-id>`。
3. 只有 `ready-candidate` 才表示可进入人工同步审阅；`needs-raw-review` / `needs-conflict-review` 仍需补证。
