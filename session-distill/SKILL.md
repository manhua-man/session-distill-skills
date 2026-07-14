---
name: session-distill
version: 1.2.0
description: |
  将 Claude Code 的 `.jsonl` 会话文件蒸馏为 packet、session note 和可复用知识。
  当用户说“整理一下对话”、“提炼会话经验”、“从 Claude 会话中提取知识”时使用。
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
---

# Session Distiller

## 定位

这是 **Claude 侧** 的 `session-distill`，只处理 Claude Code 会话，不处理
Codex rollout JSONL。

当前这份 skill 的真实输入输出是：

- 输入目录：`~/.claude/projects/<project>/*.jsonl`
- 工作区：`~/.claude/session-distill/`
- 核心产物：
  - `manifest.json`
  - `packets/<session-id>.md`
  - `distilled/sessions/<session-id>.md`
  - `knowledge-base.md`
- 可选增强产物：
  - `memory-drafts/<session-id>.json`

## 当前主链（Deep Distill）

全平台统一范式见 `references/deep-distill-workflow.md`：

1. `deep-distill-run.py --batch-size 3` → `distilled/answer-packets/`
2. answer-me：逐条 Q 用 Read/Grep/git/Shell 验证；仅 `ANSWERED` 可晋升
3. 写 `distilled/sessions/<session-id>.md`
4. `distilled/check-work/batch-*-report.md` 记录晋升/未晋升及原因
5. check-work PASS 后 `mark <session-id> distilled`

**禁止**无 answer-packet 的批量 `auto-run` / `auto-standalone` 直接晋升 KB；这两条命令仅保留作遗留 packet 预览或 memory-drafts 增强路径。

旧 note-first 链路（`run --next 1` 后直接写 KB）仅用于单条 packet 预览，不能跳过 answer-me。

## 默认循环（Deep Distill）

推荐按下面的顺序执行：

1. `deep-distill-run.py --offset <N> --batch-size 3`
2. answer-me 填每张 answer-packet 的 Results 表
3. 仅 `ANSWERED` 行写入 `knowledge-base.md` 或 repo `session-knowledge-base.md`
4. 写 `distilled/sessions/<session-id>.md`
5. 完成 `distilled/check-work/batch-*-report.md`
6. `session-distill mark <session-id> distilled`

如果这条会话不值得沉淀长期知识，在 session note 里明确写 `Do not promote`，answer-packet 对应行标 `NOT_APPLICABLE`。

## 命令

当前脚本实际支持的命令是：

```bash
python ~/.claude/skills/manhua/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py help
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py status
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py list --size 100
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py run --next 3
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py mark <session-id> distilled
# Legacy (no answer-packet gate — preview / memory-drafts only):
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py auto-run --next 3
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py auto-standalone --next 3
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py auto-standalone --next 3 --sync-claude-mem
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py self-test
```

如果你在 shell wrapper 环境里已经注册了 `session-distill`，也可以直接用：

```bash
session-distill run --next 1
session-distill status
session-distill mark <session-id> distilled
```

## 状态语义

- `new`
  - 已索引，尚未生成 packet
- `bundled`
  - packet 已生成，等待 AI 提炼
- `distilled`
  - session note 已完成，知识判断已完成
- `skipped`
  - 主动跳过，不参与当前队列

## 与 memory-drafts / claude-mem 的关系

当前要分清两层：

1. `session-distill`
   - 核心职责是把原始 Claude 会话变成 packet、session note 和
     `knowledge-base.md`

2. `packet-memory-export` / `claude-mem`
   - 属于可选增强链路
   - 适合在你已经有 packet，想导出结构化记忆候选时使用

所以真实关系是：

- `session-distill` 可以独立完成主链
- `packet-memory-export` 不是前置硬依赖
- `claude-mem` 不是默认直写后端

## 何时补看 raw

以下情况不要只信 packet：

- `Packet Audit` 显示 `Coverage: partial`
- packet 文本明显被裁剪
- 结论看起来像高风险规则、跨模块规则或容易误导别人的 workflow
- packet 只显示了 review 结论，但你需要确认中间证据、测试或真实改动面

## 提炼标准

优先写进 `knowledge-base.md` 的应该是：

- 稳定规则
- 可复用 workflow
- 跨会话仍然成立的排障经验
- 明确被代码、配置、测试或操作事实支撑的结论

不要直接提升的内容包括：

- 一次性端口、PID、临时路径
- 只适用于某个瞬时环境的 workaround
- 只是一条会话里偶然出现的操作细节
- 还没有被补证的猜测

## 参考文件

开始前优先读：

- [references/deep-distill-workflow.md](references/deep-distill-workflow.md)
- [references/distillation-rules.md](references/distillation-rules.md)
- [references/output-layout.md](references/output-layout.md)

只有在你明确要走增强链路时，再读：

- [references/claude-mem-sync.md](references/claude-mem-sync.md)

## 边界说明

这份 skill 现在描述的是 **Claude 当前真实实现**，不是 Codex 版，也不是一份
未来规划文档。

如果未来 Claude 脚本真的切成 `memory-drafts` 默认主链，再更新这份 `SKILL.md`。
在那之前，不要把 `packet-memory-export` 写成这里的默认必经步骤。
