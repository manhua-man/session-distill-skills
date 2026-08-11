---
name: session-distill
description: |
  Distill OpenCode storage sessions into review packets, local session notes,
  and reusable memory candidates. Use when the user asks to整理/提炼 OpenCode
  对话, process `~/.local/share/opencode/storage/`, generate session packets,
  review packet coverage, or mark OpenCode sessions as distilled.
argument-hint: "[status | run --next N | deep-distill | mark <id> distilled]"
user-invocable: true
---

# OpenCode Session Distiller

This is the OpenCode-native `session-distill` skill. It reads OpenCode storage
JSON trees under `storage/session`, not Claude Code / Codex / Cursor files.

## Inputs And Outputs

- Input sessions:
  - `~/.local/share/opencode/storage/session/**`
  - `~/.local/share/opencode/storage/message/**` and `storage/part/**` for message bodies
  - override home: `OPENCODE_HOME`
- Workspace:
  - `~/.local/share/opencode/session-distill/manifest.json`
  - `~/.local/share/opencode/session-distill/packets/<session-id>.md`
  - `~/.local/share/opencode/session-distill/distilled/sessions/<session-id>.md`
  - `~/.local/share/opencode/session-distill/knowledge-base.md`

## 知识库路径防护规约

- **主真值知识库 (Canonical KB)**：`E:/project/servers/.cursor/notes/conversations/session-knowledge-base.md`
- **本地 Redirect 壳文件**：`~/.opencode/session-distill/knowledge-base.md` 仅为重定向壳文件（~333B 属正常），**严禁向壳文件内写入任何知识内容**！

## Default Workflow — 全链路闭环

**完成一批 = Phase 2/3/4/5 全部跑完**，缺一不可；禁止只跑 Phase 2 就宣布完成。

- **Phase 2 批量蒸馏**：产出 `packets` + `answer-packets`（一一对应，无空产物）。
- **Phase 3 answer-me 验证**：对每个 answer-packet 的 Q 逐条分类回填 Results 表，PENDING=0。
- **Phase 4 知识晋升**：仅 Status=ANSWERED 行写入主知识库 `session-knowledge-base.md`。
- **Phase 5 check-work 报告与门禁校验**：包含 All/Unanswered/NotApplicable/Contradicted/Answered 计数，且 Note 通过 `## Final Session Review` 门禁。

> Phase 编号对应 `references/deep-distill-workflow.md`。


Follow `references/deep-distill-workflow.md` (shared across platforms):

1. `python bin/deep-distill-run.py --batch-size 3` — bundle + extract claims → `distilled/answer-packets/`
2. answer-me: verify each Q with Read/Grep/git/Shell; only `ANSWERED` promotes
3. Session note under `distilled/sessions/<session-id>.md`
4. `distilled/check-work/batch-*-report.md` with promoted / not-promoted reasons
5. `mark <session-id> distilled` after check-work PASS

Legacy one-shot flow (`run --next 1` without answer-packets) is for packet preview only — do not auto-promote to KB.

## Packet Preview (optional)

1. Run `python bin/opencode-session-distill.py run --next 1`.
2. Read the generated packet and inspect `Packet Audit` first.
3. If `Coverage: partial`, inspect raw storage JSON before promoting any conclusion.

`mark distilled` requires a session note and promotion decision. Partial packets must document raw storage review.

## Commands

```bash
export OPENCODE_DISTILL_DIR="$HOME/.local/share/opencode/session-distill"

python ~/.config/opencode/skills/session-distill/bin/deep-distill-run.py --offset 0 --batch-size 3
python ~/.config/opencode/skills/session-distill/bin/opencode-session-distill.py status
python ~/.config/opencode/skills/session-distill/bin/opencode-session-distill.py list --size 100
python ~/.config/opencode/skills/session-distill/bin/opencode-session-distill.py run --next 1
python ~/.config/opencode/skills/session-distill/bin/opencode-session-distill.py mark <session-id> distilled
python ~/.config/opencode/skills/session-distill/bin/opencode-session-distill.py self-test
```

## References

- `references/deep-distill-workflow.md`: canonical Deep Distill pipeline (all platforms).
- `references/distillation-rules.md`: promotion and filtering rules.
- `references/output-layout.md`: workspace layout and status meanings.

Use other platform distillers only for their respective session roots.


## Anti-patterns 常见误区防范

- **只跑 Phase 2 就收尾**：批量蒸馏产出 packets 不算完成，Phase 3/4/5 必须继续。
- **未经工具链校验即晋升**：Transcript 均为假设，未经 Grep/Read/git/Shell 实证禁止写入主 KB。
- **误写 Redirect 壳文件**：向本地 `knowledge-base.md` 重定向壳文件写内容，而非主 KB `session-knowledge-base.md`。
- **未分类平铺追加**：未归入对应 `## N. 模块` 或自建新领域模块，直接在文件末尾平铺堆叠散乱文本。
- **缺失终审门禁**：Session Note 缺少 `## Final Session Review` 或未通过 `validate_final_review()` 即标记 `distilled`。
- **普通 mark 时误删 Raw**：在 `mark distilled` 时硬删原始 JSONL 转录（必须使用 `prune-raw --confirm` 并保留审计日志）。
