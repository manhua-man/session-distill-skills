# Tooling Gate（开始蒸馏前必过）

> **原则：** 先工具、后干活。未通过本清单前，不要跑 `deep-distill-run` 批量蒸馏、不要删 raw、不要晋升 KB。

## 1. 单一真源

| 角色 | 路径 |
|------|------|
| 共享 core 真源 | `%USERPROFILE%\.cursor\skills\session-distill\bin\` |
| 同步脚本 | `bin\sync-distill-installs.py` |

```powershell
python $env:USERPROFILE\.cursor\skills\session-distill\bin\sync-distill-installs.py
```

成功应输出 `==> Sync OK`。

## 2. 自动化测试（全绿才算工具就绪）

```powershell
# 共享 core（revision/chunk/checkpoint/queue）
python $env:USERPROFILE\.cursor\skills\session-distill\tests\test_distill_core.py

# 跨平台共享库哈希一致
python $env:USERPROFILE\.cursor\skills\session-distill\tests\test_lib_parity.py

# 各平台 adapter self-test
python $env:USERPROFILE\.codex\skills\manhua\session-distill\bin\session-distill.py self-test
python $env:USERPROFILE\.cursor\skills\session-distill\bin\cursor-session-distill.py self-test
python $env:USERPROFILE\.grok\skills\session-distill\bin\grok-session-distill.py self-test
python $env:USERPROFILE\.claude\skills\manhua\session-distill\bin\session-distill.py self-test
python $env:USERPROFILE\AppData\Local\hermes\skills\session-distill\bin\hermes-session-distill.py self-test
python $env:USERPROFILE\.gemini\antigravity-cli\skills\session-distill\bin\antigravity-session-distill.py self-test
```

## 3. 平台 adapter 状态

| 平台 | lossless ingest | pending_redistill | final review 门禁 | deep-distill-run + chunk resume |
|------|-----------------|-------------------|-------------------|--------------------------------|
| Cursor | yes | yes | yes | yes |
| Codex | yes | yes | yes | yes |
| Grok | yes | yes | yes | yes |
| Hermes | yes | yes | yes | yes |
| Antigravity | yes | yes | yes | yes |
| Claude Code | yes | yes | yes | yes |
| OpenCode | 未安装 | — | — | — |

## 4. 通过后再做的事

1. `deep-distill-run.py --offset 0 --batch-size 3`（按平台选 runner）
2. answer-me 验证每个 Q
3. 写 session note（含 `## Final Session Review`）
4. `mark distilled`
5. 可选：Cursor 清理用 `cleanup-cursor-distill.py`（与 mark 分离）

## 5. 明确不做

- 不在 `servers` 仓库放 distill 工具脚本
- 不在工具未同步时手工复制 `deep_distill_lib.py`
- 不从裁剪 packet 直接晋升 KB（`Coverage: partial` 或仅有 preview）
