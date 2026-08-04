---
description: Prepare Grok transcript packets, then distill them into reusable knowledge
argument-hint: "[status | run --next N | list | mark <id> distilled | 自然语言请求]"
user-invocable: true
---

Use the Grok `session-distill` workflow.

Mental model:

1. `chat_history.jsonl` -> packet
2. packet -> session note + reusable patterns
3. reusable patterns -> repo rules / module docs only when the destination is clear

Always load when distilling:

- `~/.grok/skills/session-distill/SKILL.md`
- `~/.grok/skills/session-distill/references/distillation-rules.md`

Script (user scope):

```powershell
python $env:USERPROFILE\.grok\skills\session-distill\bin\grok-session-distill.py <input>
```

If this repo also installs the skill locally, you may use:

```powershell
python .grok/skills/session-distill/bin/grok-session-distill.py <input>
```

---

**Input**

The argument after `/session-distill` can be either:

- a direct script command such as `status`, `run --next 3`, `list --size 0`, or `mark <session-id> distilled`
- a natural-language request such as `distill the latest 3 sessions and extract reusable review heuristics`

By default, scan **all projects** under `~/.grok/sessions/`.
Use `--project <keyword>` only when you want to narrow to one repo, for example `--project servers`.

---

## Command Routing

1. If the input starts with one of these commands:

   - `run`
   - `status`
   - `list`
   - `mark`
   - `index`
   - `help`

   then execute the matching script directly.

2. If no input is provided:

   run `status`, summarize the queue, and tell the user the next obvious command.

3. If the input is natural language:

   first prepare packets with `run --next 3` (no `--project` unless the user named a repo),
   then read the newly bundled packets and perform distillation.

---

## Distillation Behavior

1. Prefer packet reading over raw `chat_history.jsonl`.
2. Treat the packet as the default evidence layer.
3. Extract reusable workflow, command patterns, file maps, debugging entrypoints, promotion candidates.
4. Use `references/distillation-rules.md` before promoting anything.
5. Keep session note, knowledge base, and repo rules as separate layers.
6. If the destination is unclear, record a `promotion candidate` instead of editing repo rules.

---

## Guardrails

- Do not silently treat business logic facts as repo-wide AI rules.
- Do not skip the layer-classification step.
- `mark distilled` keeps raw Grok session files by default; use `--delete-raw` only when the user explicitly wants removal.