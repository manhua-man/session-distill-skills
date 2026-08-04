# Grok Session Format

Grok CLI stores each session under:

`~/.grok/sessions/<url-encoded-project-path>/<session-id>/`

Common files:

- `chat_history.jsonl`: primary transcript source for packets.
- `summary.json`: title, cwd, model, git metadata, timestamps.
- `events.jsonl`, `updates.jsonl`: optional live update streams (not required for v1 packets).

`chat_history.jsonl` record types:

- `system`: bootstrap prompt; ignored as content.
- `user`: request text, often wrapped in IDE context; extract `<user_query>` when present.
- `reasoning`: encrypted reasoning is not a content source; optional summary text may be noted.
- `assistant`: assistant text plus `tool_calls`.
- `tool_result`: tool output linked by `tool_call_id`.

Packet rules:

- Ignore giant injected context blocks (`<user_info>`, `<git_status>`, `<rules>`) after extracting the real user query.
- Render user messages, assistant updates, tool calls, and tool outputs.
- Clip large text/tool output and mark packet coverage as `partial`.
- Include file references discovered in rendered content.
- Treat `summary.json` as metadata for title, cwd, model, and git state.