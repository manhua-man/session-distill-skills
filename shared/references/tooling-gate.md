# Tooling Gate（开始蒸馏前必过）

> **原则：** 先工具、后干活。未通过本清单前，不要跑 `deep-distill-run` 批量蒸馏、不要删 raw、不要晋升 KB。

## 1. 单一真源

| 角色 | 路径 |
|------|------|
| 共享 core 真源（开发） | `session-distill-skills/shared/distill_core/` |
| 本机安装同步 | `%USERPROFILE%\.cursor\skills\session-distill\bin\sync-distill-installs.py` |
| 仓库内 vendored 同步 | `python scripts/sync-repo-distill-core.py` |

## 2. 自动化测试（全绿才算工具就绪）

```powershell
cd E:\project\session-distill-skills
python scripts\run-all-tests.py
```

等价于：同步 `distill_core` → 八套 adapter `self-test` → `test_distill_core` → contract 测试。

根目录 `pytest -q` 仅收集 `tests/`（不会误扫各平台 `test_core.py` 导致 import 冲突）。

## 3. 平台 adapter 状态

| 平台 | lossless ingest | pending_redistill | final review 门禁 | prune-raw 审计 |
|------|-----------------|-------------------|-------------------|----------------|
| Cursor | yes | yes | yes | N/A（cleanup 独立） |
| Codex | yes | yes | yes | yes |
| Grok | yes | yes | yes | yes |
| Hermes | yes | yes | yes | N/A |
| Antigravity | yes | yes | yes | N/A |
| Claude Code | yes | yes | yes | N/A |
| OpenCode | yes | yes | yes | N/A |

## 4. 通过后再做的事

1. `deep-distill-run.py --offset 0 --batch-size 3`（按平台选 runner）
2. answer-me 验证每个 Q
3. 写 session note（含 `## Final Session Review`）
4. `mark distilled`
5. `packet-memory-export sync-list`（需 distilled note `Promotion allowed: yes`）
6. 可选：Cursor 清理用 `cleanup-cursor-distill.py`（与 mark 分离）

## 5. 明确不做

- 不在 `servers` 仓库放 distill 工具脚本
- 不在工具未同步时手工复制 `deep_distill_lib.py`
- 不从裁剪 packet 直接晋升 KB（`Coverage: partial` 或仅有 preview）
- 不在 `mark distilled` 时删除 raw（用 `prune-raw --confirm`）
