---
name: packet-memory-export
version: 1.0.0
description: |
  从 session-distill 生成的 packet 中导出结构化 draft memory entries。
  当用户说"把 packet 变成 memory draft"、"导出记忆候选"、"为 Codex-mem 准备同步候选"时使用。
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
---

# Packet Memory Exporter

## 定位

`packet-memory-export` 是 `session-distill` 的 sibling sidecar。

它只负责：

1. 读取 `~/.codex/session-distill/packets/<session-id>.md`
2. 产出结构化 draft memory entries
3. 根据标签和 `Packet Audit` 把结果分成 ready candidates / blocked review / conflicts / local-only
4. 作为 `session-distill` 默认的 promotion gate

它不负责：

- 解析原始 `~/.codex/projects/*.jsonl`
- 生成 packet / manifest
- 直接写回 Codex-mem
- 强制要求所有 draft 都接入额外协作 skill

## 输入和输出

输入：

- `~/.codex/session-distill/packets/<session-id>.md`
- 可选的现有 memory 导出文件，用于 `confirm / refine / conflict` 启发式判定

输出：

- `~/.codex/session-distill/memory-drafts/<session-id>.json`

默认导出的 JSON 还会附带：

- `label_counts`
- `readiness_counts`
- `sync_candidates`
- `blocked_sync_candidates`
- `conflict_ids`
- `local_only_ids`

## 什么时候使用

| 场景 | 使用哪个 skill |
|------|----------------|
| 还没有 packet，只是原始 `.jsonl` | `session-distill` |
| 已经有 packet，想导出 memory drafts | `packet-memory-export` |

## 默认流程

1. 先用 `session-distill run --next N` 生成 packet
2. 读 packet 顶部的 `Packet Audit`
3. 运行 `packet-memory-export export --session <session-id>`
4. 运行 `packet-memory-export review --session <session-id>`
5. 审阅 `new / refine / confirm / conflict / ephemeral`
6. 按 `ready-candidate / needs-raw-review / needs-conflict-review / local-only` 分队列处理
7. 用 `approve / reject / defer / note` 把人工判断落回 draft JSON
8. `conflict` 先人工复核
9. 如果已安装且当前 draft 需要额外协作，可选接入：
   - `grill-me`
   - `answer-me`
10. 需要时用 `approve-batch / reject-batch` 加速处理
11. 生成或刷新 `sync-list`
12. `ephemeral` 只留本地，不进 sync candidates
13. 如果目标已经变成整理既有 `Codex-mem observations`，切到 `mem-distill`

这里的关键规则是：

- `Coverage: high`
  - 通常更容易得到 `ready-candidate`
- `Coverage: partial`
  - 仍然可以正常导出 `memory-drafts`
  - 只是默认更保守，常见为 `needs-raw-review` 或 `local-only`

也就是说，`partial` 会降低 readiness，但不会把你赶回另一条主链。

## 可选协作者

这些能力在已安装且场景匹配时才接入，不是默认硬依赖：

- `grill-me`
  - 对高风险、重要、争议大的 draft 做压力测试
- `answer-me`
  - 对证据不足的 draft 做代码 / 文档 / 配置补证

## 常用命令

```bash
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py status
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py list
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py export --session <session-id>
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py review --session <session-id>
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py approve --session <session-id> --entry <entry-id>
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py approve-batch --session <session-id> --review-status pending --readiness ready-candidate
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py reject --session <session-id> --entry <entry-id> --note "why"
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py reject-batch --session <session-id> --entries <id1,id2> --note "why"
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py defer --session <session-id> --entry <entry-id> --note "follow-up"
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py note --session <session-id> --entry <entry-id> --note "comment"
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py sync-list --session <session-id>
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py export --session <session-id> --memory existing-memory.json
python ~/.codex/skills/manhua/packet-memory-export/bin/packet-memory-export.py self-test
```

## Review Queue

- `pending`
  - 默认状态，表示这条 draft 还没被人工确认
- `approved`
  - 这条 draft 已被人工确认，可以进入后续同步准备
- `rejected`
  - 这条 draft 不应该继续进入同步队列
- `deferred`
  - 暂时保留，但需要更多上下文或等待后续时机

每条 entry 还会保留：

- `review_note`
- `reviewed_at`
- `review_log`

这样 review 不只是终端输出，而是会回写到 `memory-drafts/<session-id>.json`。

如果当前 draft 里存在同时满足下面条件的 entry：

- `review_status = approved`
- `sync_readiness = ready-candidate`
- `label in {new, refine, confirm}`

那么 exporter 还会自动派生：

- `~/.codex/session-distill/sync-lists/<session-id>.json`

这个文件就是“待同步清单”，适合作为后续人工同步 Codex-mem 的输入。

## 标签规则

- `new`
  - 当前没看到足够接近的旧 memory，可作为新增候选
- `refine`
  - 和现有 memory 接近，但表达或约束值得更新
- `confirm`
  - 和现有 memory 高度一致，可作为再次验证
- `conflict`
  - 和现有 memory 高相似但有明显冲突信号，必须人工复核
- `ephemeral`
  - 只对当前任务有意义，不进入稳定同步候选

## 工作边界

- `packet-memory-export` 是默认 draft gate，但不是自动同步器
- `Packet Audit: partial` 时，不把导出的 `new / refine / confirm` 自动视为可同步
- `ready-candidate` 才是当前可继续进入人工同步审阅的候选
- `needs-raw-review` / `needs-conflict-review` 都表示还不能直接往下走
- 第一阶段只产出结构化 JSON，不自动写回 Codex-mem
- `grill-me / answer-me / mem-distill` 如果不可用，就直接跳过，不阻塞主链
- 如果需要真正整理已同步后的 observations，切回 `mem-distill`
