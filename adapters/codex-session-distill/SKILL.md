---
name: session-distill
description: |
  Distill Codex session JSONL files into review packets, local session notes,
  and reusable memory candidates. Use when the user asks to整理/提炼 Codex
  对话, process `.codex/archived_sessions` or `.codex/sessions` rollouts,
  generate session packets, review packet coverage, or mark Codex sessions as
  distilled.
---

# Codex Session Distiller

This is the Codex-native `session-distill` skill. It reads Codex rollout
JSONL, not Claude Code session files.

## Inputs And Outputs

- Input sessions:
  - `~/.codex/archived_sessions/rollout-*.jsonl`
  - `~/.codex/sessions/**/*.jsonl`
  - `~/.codex/session_index.jsonl` for thread names when available
- Workspace:
  - `~/.codex/session-distill/manifest.json`
  - `~/.codex/session-distill/packets/<session-id>.md`
  - `~/.codex/session-distill/distilled/sessions/<session-id>.md`
  - `~/.codex/session-distill/knowledge-base.md`
  - optional `~/.codex/session-distill/memory-drafts/<session-id>.json`

## 知识库路径防护规约

- **主真值知识库 (Canonical KB)**：`E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md`
- **本地 Redirect 壳文件**：`~/.codex/session-distill/knowledge-base.md` 仅为重定向壳文件（~333B 属正常），**严禁向壳文件内写入任何知识内容**！

## Default Workflow — 全链路闭环

**完成一批 = Phase 2/3/4/5 全部跑完**，缺一不可；禁止只跑 Phase 2 就宣布完成。

- **Phase 2 批量蒸馏**：产出 `packets` + `answer-packets`（一一对应，无空产物）。
- **Phase 3 answer-me 验证**：对每个 answer-packet 的 Q 逐条分类回填 Results 表，PENDING=0。
- **Phase 4 知识晋升**：仅 Status=ANSWERED 行写入主知识库 `session-knowledge-base.md`。
- **Phase 5 check-work 报告与门禁校验**：包含 All/Unanswered/NotApplicable/Contradicted/Answered 计数，且 Note 通过 `## Final Session Review` 门禁。

> Phase 编号对应 `references/deep-distill-workflow.md`。


### Deep Distill (servers, recommended)

```powershell
python ~/.codex/skills/manhua/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3
```

Then: answer-me verify → promote ANSWERED only → `session-knowledge-base.md` §Codex → check-work → `mark distilled`.

See `references/deep-distill-workflow.md`.

### Legacy single-session flow

1. Run `python ~/.codex/skills/manhua/session-distill/bin/session-distill.py run --next 1`.
2. Read the generated packet and inspect `Packet Audit` first.
3. If `Coverage: partial`, inspect the raw JSONL span before promoting any conclusion.
4. Write a session note under `distilled/sessions/<session-id>.md`.
5. Append only stable reusable knowledge to `knowledge-base.md`, or explicitly record no promotion.
6. Before marking distilled, run a lightweight knowledge review when you promoted anything:
   `python ~/.codex/skills/manhua/session-distill/bin/session-distill.py review-kb --next 20 --query <session-id-or-topic>`
7. If memory drafts exist, review every entry so none remain `pending`.
8. Run `python ~/.codex/skills/manhua/session-distill/bin/session-distill.py mark <session-id> distilled`.
   This retains the original Codex rollout JSONL. If it is ever necessary to
   remove raw data, use the separate audited `prune-raw <session-id> --confirm`
   command with a reason.

The `mark distilled` command has guardrails: it fails unless the note exists,
partial packets mention raw review, memory drafts have no pending entries, and
the note records a promotion decision. If `knowledge-base.md` already contains
entries sourced from the same session, obvious volatile or weak entries are also
rejected unless you use `--force`. Raw-file deletion still only applies under
`~/.codex/archived_sessions` or `~/.codex/sessions`.

## Commands

```bash
python ~/.codex/skills/manhua/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py status
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py list --size 100
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py run --next 1
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py mark <session-id> distilled
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py prune-raw <session-id> --confirm --reason "retention policy"
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py review-kb --next 20
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py verify-entry <session-id|keyword>
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py prune-kb --statuses stale,superseded
python ~/.codex/skills/manhua/session-distill/bin/session-distill.py self-test
```

## References

- `references/codex-session-format.md`: Codex JSONL event shapes and packet rules.
- `references/deep-distill-workflow.md`: Grok-paradigm batch pipeline for servers.
- `references/distillation-rules.md`: promotion and filtering rules.
- `references/output-layout.md`: workspace layout and status meanings.

Use the older Claude session distiller only for `~/.claude/projects/*.jsonl`.


## Anti-patterns 常见误区防范

- **只跑 Phase 2 就收尾**：批量蒸馏产出 packets 不算完成，Phase 3/4/5 必须继续。
- **未经工具链校验即晋升**：Transcript 均为假设，未经 Grep/Read/git/Shell 实证禁止写入主 KB。
- **误写 Redirect 壳文件**：向本地 `knowledge-base.md` 重定向壳文件写内容，而非主 KB `session-knowledge-base.md`。
- **未分类平铺追加**：未归入对应 `## N. 模块` 或自建新领域模块，直接在文件末尾平铺堆叠散乱文本。
- **缺失终审门禁**：Session Note 缺少 `## Final Session Review` 或未通过 `validate_final_review()` 即标记 `distilled`。
- **普通 mark 时误删 Raw**：在 `mark distilled` 时硬删原始 JSONL 转录（必须使用 `prune-raw --confirm` 并保留审计日志）。
- **仅按 Session Title 粗粒度提取 Claim**：禁止仅抓取会话首轮标题，必须递归扫描多轮对话中 Assistant 的 `final_answers`、代码补丁与核心排查结论。

