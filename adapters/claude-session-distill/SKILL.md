---
name: claude-session-distill
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

## 当前主链

默认不要把它理解成 “raw session -> memory-drafts -> 直接同步记忆”。

当前脚本的真实主链是：

1. `run --next N` 生成 packet
2. AI 先读 packet，并先看 `Packet Audit`
3. 如果 `Coverage: partial`，再补看 raw `.jsonl`
4. AI 写 `distilled/sessions/<session-id>.md`
5. AI 把稳定知识追加到 `knowledge-base.md`
6. AI 运行 `mark <session-id> distilled`

也就是说，**当前默认主链是 note-first**：

- `packet -> session note -> knowledge-base -> mark`

`packet-memory-export` 和 `memory-drafts` 目前属于增强路径，不是这个
Claude skill 的默认 promotion gate。

## 默认循环

推荐按下面的顺序执行：

1. `session-distill run --next 1`
2. 只读一个新 packet
3. 先看 `Packet Audit`
4. 如果 `Coverage: partial`，打开原始 `.jsonl` 补证
5. 写 `distilled/sessions/<session-id>.md`
6. 只把稳定、可复用的规则追加进 `knowledge-base.md`
7. 运行 `session-distill mark <session-id> distilled`

如果这条会话不值得沉淀长期知识，也要在 session note 里明确写出
`Do not promote` 一类结论，而不是跳过判断。

## 命令

当前脚本实际支持的命令是：

```bash
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py help
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py status
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py list --size 100
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py run --next 3
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py mark <session-id> distilled
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

- [references/distillation-rules.md](references/distillation-rules.md)
- [references/output-layout.md](references/output-layout.md)

只有在你明确要走增强链路时，再读：

- [references/claude-mem-sync.md](references/claude-mem-sync.md)

## 边界说明

这份 skill 现在描述的是 **Claude 当前真实实现**，不是 Codex 版，也不是一份
未来规划文档。

如果未来 Claude 脚本真的切成 `memory-drafts` 默认主链，再更新这份 `SKILL.md`。
在那之前，不要把 `packet-memory-export` 写成这里的默认必经步骤。


## 知识库路径防护规约

- **主真值知识库 (Canonical KB)**：`E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md`
- **本地 Redirect 壳文件**：`~/.claude/session-distill/knowledge-base.md` 仅为重定向壳文件（~333B 属正常），**严禁向壳文件内写入任何知识内容**！

## Default Workflow — 全链路闭环

**完成一批 = Phase 2/3/4/5 全部跑完**，缺一不可；禁止只跑 Phase 2 就宣布完成。

- **Phase 2 批量蒸馏**：产出 `packets` + `answer-packets`（一一对应，无空产物）。
- **Phase 3 answer-me 验证**：对每个 answer-packet 的 Q 逐条分类回填 Results 表，PENDING=0。
- **Phase 4 知识晋升**：仅 Status=ANSWERED 行写入主知识库 `session-knowledge-base.md`。
- **Phase 5 check-work 报告与门禁校验**：包含 All/Unanswered/NotApplicable/Contradicted/Answered 计数，且 Note 通过 `## Final Session Review` 门禁。

> Phase 编号对应 `references/deep-distill-workflow.md`。


## Anti-patterns 常见误区防范

- **只跑 Phase 2 就收尾**：批量蒸馏产出 packets 不算完成，Phase 3/4/5 必须继续。
- **未经工具链校验即晋升**：Transcript 均为假设，未经 Grep/Read/git/Shell 实证禁止写入主 KB。
- **误写 Redirect 壳文件**：向本地 `knowledge-base.md` 重定向壳文件写内容，而非主 KB `session-knowledge-base.md`。
- **未分类平铺追加**：未归入对应 `## N. 模块` 或自建新领域模块，直接在文件末尾平铺堆叠散乱文本。
- **缺失终审门禁**：Session Note 缺少 `## Final Session Review` 或未通过 `validate_final_review()` 即标记 `distilled`。
- **普通 mark 时误删 Raw**：在 `mark distilled` 时硬删原始 JSONL 转录（必须使用 `prune-raw --confirm` 并保留审计日志）。
