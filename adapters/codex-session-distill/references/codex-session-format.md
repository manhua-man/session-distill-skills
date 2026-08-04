# Codex Session Format

Codex rollout JSONL commonly uses these outer event types:

- `session_meta`: session id, cwd, source, model provider, git metadata.
- `turn_context`: starts a turn and carries `turn_id`, cwd, model, date, mode.
- `event_msg`: user messages, agent commentary, token counts, task lifecycle,
  patch apply summaries.
- `response_item`: assistant messages, tool calls, tool outputs, reasoning
  placeholders, custom tool calls.

Packet rules:

- Ignore giant base instructions and encrypted reasoning as content sources.
- Render user messages, assistant commentary, final answers, plans, tool calls,
  tool outputs, and patch summaries.
- Clip large text/tool output and mark packet coverage as `partial`.
- Include file references discovered in rendered content.
- Treat `.codex/session_index.jsonl` as optional metadata for thread names.
