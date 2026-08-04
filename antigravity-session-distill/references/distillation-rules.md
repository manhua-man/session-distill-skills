# Distillation Rules

Promote only stable, reusable knowledge verified against current repo/runtime into the target project's canonical knowledge base (`session-knowledge-base.md`).

## Deep Distill promotion gate

Before any KB / docs / AGENTS edit:

1. Run `deep-distill-run.py` to create `distilled/answer-packets/<session-id>.md`.
2. Verify each Q with toolchain evidence (Read/Grep/git/Shell).
3. Only rows with Status=`ANSWERED` may promote.
4. **Dynamic Topic Classification**: Categorize promoted entries by **Functional Domain / Topic** based on the target project's actual module architecture (e.g. Deploy, Auth, Payment, Core Business Modules), rather than creating platform-specific or batch-specific headers.
5. **Freshness Timestamp Formatting**: Format promoted entries with verification date only: `- **标题**: 验证后的稳定知识结论 (verified YYYY-MM-DD).` Do **not** append raw conversation `Source ID` tags.
6. Complete `distilled/check-work/batch-*-report.md` before `mark distilled`.

Chat/packet text is hypotheses until verified. If nothing passes, write `No Promotion` in the session note.


