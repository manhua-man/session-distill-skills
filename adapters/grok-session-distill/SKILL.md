---
name: session-distill
description: |
  Distill Grok CLI session JSONL files into review packets, local session notes,
  and reusable memory candidates. Use when the user asks to整理/提炼 Grok
  对话, runs /session-distill, processes `~/.grok/sessions` chat history,
  generates session packets, reviews packet coverage, or marks Grok sessions
  as distilled.
argument-hint: "[status | run --next N | list | mark <id> distilled]"
user-invocable: true
---

# Grok Session Distiller

This is the Grok-native `session-distill` skill. It reads Grok CLI
`chat_history.jsonl`, not Claude Code / Codex / Cursor session files.

## Inputs And Outputs

- Input sessions:
  - `~/.grok/sessions/<encoded-project>/<session-id>/chat_history.jsonl`
  - `~/.grok/sessions/<encoded-project>/<session-id>/summary.json` for metadata
- Workspace:
  - `~/.grok/session-distill/manifest.json`
  - `~/.grok/session-distill/packets/<session-id>.md`
  - `~/.grok/session-distill/distilled/sessions/<session-id>.md`
  - `E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md` (canonical; `SESSION_DISTILL_KB` to override)

## 知识库路径防护规约

- **主真值知识库 (Canonical KB)**：`E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md`
- **本地 Redirect 壳文件**：`~/.grok/session-distill/knowledge-base.md` 仅为重定向壳文件（~333B 属正常），**严禁向壳文件内写入任何知识内容**！

## Default Workflow — 全链路闭环

**完成一批 = Phase 2/3/4/5 全部跑完**，缺一不可；禁止只跑 Phase 2 就宣布完成。

- **Phase 2 批量蒸馏**：产出 `packets` + `answer-packets`（一一对应，无空产物）。
- **Phase 3 answer-me 验证**：对每个 answer-packet 的 Q 逐条分类回填 Results 表，PENDING=0。
- **Phase 4 知识晋升**：仅 Status=ANSWERED 行写入主知识库 `session-knowledge-base.md`。
- **Phase 5 check-work 报告与门禁校验**：包含 All/Unanswered/NotApplicable/Contradicted/Answered 计数，且 Note 通过 `## Final Session Review` 门禁。

> Phase 编号对应 `references/deep-distill-workflow.md`。


**Shallow (packet prep):**

1. Run `python ~/.grok/skills/session-distill/bin/grok-session-distill.py run --next 1`.
2. Read the generated packet and inspect `Packet Audit` first.

**Deep (servers backlog — preferred):**

1. `python ~/.grok/skills/session-distill/bin/deep-distill-run.py --batch-size 3 --offset N`
2. For each session, complete `distilled/answer-packets/<id>.md` using **answer-me** + toolchain (`Grep`/`Read`/`git`/`Shell`; optional `mcp-search`).
3. Promote **only** `ANSWERED` rows → canonical `session-knowledge-base.md` (§I) / `docs/` / `AGENTS.md` / steering.
4. Run **check-work** subagent on promotion diffs; on `VERDICT: FAIL`, fix or demote before closing batch.
5. Write `distilled/sessions/<session-id>.md` with promotion decision.
6. `mark <session-id> distilled`.

See `references/deep-distill-workflow.md` and `references/distillation-rules.md`. Chat history is never evidence.

Unlike Codex, Grok keeps live session state under `~/.grok/sessions`.
`mark distilled` keeps raw files by default. Use `--delete-raw` only when you
intentionally want to remove `chat_history.jsonl` after review.

## Slash Command Routing

`/session-distill` should behave like Cursor's `.cursor/commands/session-distill.md`:

- script subcommands (`status`, `run`, `list`, `mark`, `index`) -> run the Python CLI directly
- no args -> `status`
- natural language -> `run --next 3` first, then read packets and distill

Default scope is **all projects** under `~/.grok/sessions/`.
Use `--project <keyword>` only to narrow to one repo.

See `commands/session-distill.md` for the user-invocable slash command definition.

## Commands

```bash
python ~/.grok/skills/session-distill/bin/grok-session-distill.py status
python ~/.grok/skills/session-distill/bin/grok-session-distill.py list --size 0
python ~/.grok/skills/session-distill/bin/grok-session-distill.py run --next 3
python ~/.grok/skills/session-distill/bin/grok-session-distill.py run --project servers --next 3
python ~/.grok/skills/session-distill/bin/grok-session-distill.py mark <session-id> distilled
python ~/.grok/skills/session-distill/bin/grok-session-distill.py mark <session-id> distilled --delete-raw
python ~/.grok/skills/session-distill/bin/grok-session-distill.py self-test
```

## References

- `references/grok-session-format.md`: Grok JSONL event shapes and packet rules.
- `references/distillation-rules.md`: promotion and filtering rules.
- `references/output-layout.md`: workspace layout and status meanings.

Use the Claude / Codex / Cursor distillers only for their respective session roots.

## Anti-patterns 常见误区防范

- **只跑 Phase 2 就收尾**：批量蒸馏产出 packets 不算完成，Phase 3/4/5 必须继续。
- **未经工具链校验即晋升**：Transcript 均为假设，未经 Grep/Read/git/Shell 实证禁止写入主 KB。
- **误写 Redirect 壳文件**：向本地 `knowledge-base.md` 重定向壳文件写内容，而非主 KB `session-knowledge-base.md`。
- **未分类平铺追加**：未归入对应 `## N. 模块` 或自建新领域模块，直接在文件末尾平铺堆叠散乱文本。
- **缺失终审门禁**：Session Note 缺少 `## Final Session Review` 或未通过 `validate_final_review()` 即标记 `distilled`。
- **普通 mark 时误删 Raw**：在 `mark distilled` 时硬删原始 JSONL 转录（必须使用 `prune-raw --confirm` 并保留审计日志）。
