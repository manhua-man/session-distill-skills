# Distillation Rules

Promote only stable, reusable knowledge verified against current repo/runtime into the target project's canonical knowledge base (`session-knowledge-base.md`).

## Deep Distill promotion gate

Before any KB / docs / AGENTS edit:

1. Run `deep-distill-run.py` to create `distilled/answer-packets/<session-id>.md`.
2. Verify each Q with toolchain evidence (Read/Grep/git/Shell).
3. Only rows with Status=`ANSWERED` may promote.
4. **Dynamic Topic Classification**: Categorize promoted entries by **Functional Domain / Topic** based on the target project's actual module architecture (e.g. Deploy, Auth, Payment, Core Business Modules), rather than creating platform-specific or batch-specific headers.
5. **Freshness Timestamp Formatting**: Format promoted entries with verification date only: `- **标题**: 验证后的稳定知识结论 (verified YYYY-MM-DD).` Do **not** append raw conversation `Source ID` tags.
6. **Temporal Staleness Audit (时效性与历史时间差审计)**: 历史会话距离当前时间越久，结论越可能过时或被后续代码覆盖。Agent **必须以当前最新代码库 HEAD 为唯一真理**。对于历史 Session 中的 Claim，必须使用 `Grep`/`Read` 在当前代码库中重新核验；若已有新重构或废弃，标记为 `STALE` / `CONTRADICTED` 拒绝晋升！
7. Complete `distilled/check-work/batch-*-report.md` before `mark distilled`.

Chat/packet text is hypotheses until verified. If nothing passes, write `No Promotion` in the session note.