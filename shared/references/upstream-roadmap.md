# Session Distill 上游迭代路线图

> **基线：** `session-distill-skills` @ `d15bdd5`（2026-07-14）  
> **核对日期：** 2026-07-15（审计缺口一次性闭合）  
> **目的：** 把 Deep Distill 从「裁剪摘要 packet」升级为可审计、可恢复、可增量重跑的 lossless pipeline。

---

## 现状摘要（2026-07-15 审计闭合后）

| 主题 | 现状 |
|------|------|
| Packet 形态 | **lossless**：七平台 `ingest_revision` + chunk/raw；OpenCode 已迁移 |
| Revision 标识 | **内容哈希**：`revision_id` 仅由 canonical transcript 决定；`source_fingerprint` 仅用于 index 增长检测 |
| distilled 后增长 | `pending_redistill` + `last_distilled_revision_id`（含 OpenCode） |
| Chunk 恢复 | `extract-checkpoints.json` 原子写入；`failed` 状态 + 续跑测试 |
| Final review | `validate_final_review` + `promotion_allowed`；`mark distilled` 与 `packet-memory-export sync-list` 双门禁 |
| 候选 ID | `make_candidate_id`；exporter 不再使用 `{session_id}-{index}` |
| Raw 删除 | **仅** `prune-raw --confirm`（Codex/Grok）；`mark` 永不删 raw |
| 共享 core | `shared/distill_core/` + `scripts/sync-repo-distill-core.py` + `sync-distill-installs.py` |
| Contract | `contracts/*.yaml`（七平台）+ `tests/contract/test_contracts.py` |
| 测试 | `scripts/run-all-tests.py`；根 `pytest.ini` 仅收集 `tests/`；无硬编码用户路径 |

---

## 实现进度

| 项 | 状态 | 备注 |
|----|------|------|
| §1 lossless revision + chunks | **已闭合** | 含 OpenCode |
| §2 内容哈希 revision | **已闭合** | touch mtime 不改变 `revision_id` |
| §3 distilled 增长再入队 | **已闭合** | 七平台 `pending_redistill` |
| §4 chunk checkpoint | **已闭合** | 原子 save + failed 状态 |
| §5 final-session review | **已闭合** | mark + exporter promotion gate |
| §6 幂等 candidate ID | **已闭合** | exporter 使用 `make_candidate_id` |
| §7 raw 默认不删 | **已闭合** | 移除 mark `--delete-raw` |
| §8 七平台 contract | **已闭合** | `contracts/*.yaml` + contract 测试 |
| §9 测试可移植 | **已闭合** | 全平台 `Path(__file__)` + temp home |
| §10 共享 core | **已闭合** | repo sync 脚本 + parity 测试 |

**门禁：** 见 `tooling-gate.md` — `python scripts/run-all-tests.py` 全绿后再跑 `deep-distill-run`。

---

*本文档为上游需求真源；实现落在 `session-distill-skills` 仓库，发布后同步到各 `~/.{cursor,codex,...}/skills/session-distill/`。*
