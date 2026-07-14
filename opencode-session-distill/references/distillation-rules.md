# Distillation Rules

Promote only stable, reusable knowledge verified against current repo/runtime.

## Deep Distill promotion gate

Before any KB / docs / AGENTS edit:

1. Run `deep-distill-run.py` to create `distilled/answer-packets/<session-id>.md`.
2. Verify each Q with toolchain evidence (Read/Grep/git/Shell).
3. Only rows with Status=`ANSWERED` may promote.
4. Complete `distilled/check-work/batch-*-report.md` before `mark distilled`.

Chat/packet text is hypotheses until verified. If nothing passes, write `No Promotion` in the session note.
