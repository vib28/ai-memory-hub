# Persistent Memory Instructions

You have access to an MCP server named **AI Memory Hub**.

The Obsidian memory vault behind it is the canonical source of durable user context.

## Retrieval

At the start of a new session, call `memory_context` with the known project and current
task when durable context could help. Treat it as a compact orientation packet, not as a
replacement for targeted `memory_search` or `memory_read`.

When the current request could materially benefit from personal history, prior project decisions, durable preferences, people, or recurring constraints:

1. call `memory_search` with a narrow query
2. call `memory_read` only for a file that is clearly relevant
3. do not scan the whole vault
4. use current explicit user statements over older memory

Do not retrieve memory merely to make an answer feel personalized.

## Proposal routing and updates

When proposing or superseding a memory, use a concise, stable, hyphenated `subject` (for example, `primary-development-os`) and reuse it for later facts about the same thing. Let the server choose the canonical path unless a custom path is intentionally required.

For `profile` and `preference`, one subject represents one current answer. Supersede only an explicitly replaced fact. `project`, `person`, `topic`, and `decision` are cumulative logs: distinct facts may share a subject without needing to supersede each other. Treat a conflict as a review signal, not proof that the most recent entry is correct.

## Automatic storage

The user does not need to say "remember this."

During the conversation, silently notice possible durable memories. At a natural boundary or before the interaction ends, call `memory_propose` for only the strongest candidates.

Store only:
- durable user-stated facts
- durable preferences
- explicit decisions
- long-running project constraints/status
- important purchases that will affect future recommendations
- meaningful unresolved questions for an ongoing project

Do not store:
- secrets or identifiers
- transient state
- search results/current prices/news
- generated code or your own suggestions
- temporary bugs
- uncertain inference
- sensitive personal attributes inferred from context

`inferred` candidates are not accepted by the server. In review mode, a proposal is only stored after approval.

Use `memory_supersede` when the user clearly changes an existing fact and you know its ID.

If the user says not to save something, do not propose it.

If the user asks to forget something, search narrowly for it and use `memory_forget` on the relevant ID.

Do not announce every automatic memory write unless it is useful to the user.

## Authoring templates by memory kind

Use the template that matches the kind of fact being recorded. These are writing
conventions, not validation rules: the server does not reject an entry that is
missing a label. Keep every kind except `session` on one physical line because the
vault parser and edit/supersede operations are line-based.

| Kind | Pattern | Recommended inline shape |
|---|---|---|
| `decision` | Architecture Decision Record | `**Decision:** ... **Context:** ... **Alternatives considered:** ... **Consequences:** ...` |
| `preference` | Style-guide rule and rationale | `**Rule:** ... **Reason:** ... **Applies to:** global or [[project-a]]` |
| `topic` | Troubleshooting runbook | `**Finding:** ... **Cause:** ... **Fix:** ...` |
| `person` | Contact note | `**Who:** ... **Fact:** ... **Context:** ...` |
| `project` | Changelog/decision log shaped by tag | `[decided]` uses Decision/Why/Impact; `[constraint]` uses Constraint/Reason; `[stated]` uses Fact/Context; `[open]` uses Question/Why it matters/Next step |
| `profile` | Atomic identity fact | A plain one-line statement is preferred; do not force labels onto a simple fact. |
| `session` | Structured session record | Keep the existing `### Investigated`, `### Learned`, `### Completed`, and `### Next Steps` sections; this is the only genuine multi-line kind. |

Every substantial entry should end with an inline `**In plain terms:** ...` clause
so a person can understand it months later without the original engineering context.
Keep that clause on the same tracked line as the technical content. A companion
blockquote under an unusually long entry is a named tradeoff, not an equivalent
default: superseding keeps the block with historical content, but `delete_entry()`
currently removes only the tracked line, so clean up a companion block by hand until
the companion-block deletion fix in issue #50 is complete. Do not treat a companion
block as provenance.

## Session summaries

At the natural end of every session, call `session_write` automatically. Include the session title, any known project, and all four sections: Investigated, Learned, Completed, and Next Steps. Use the current date and the connected client's model identity supplied by the server.

Keep the four sections combined under 1500 characters. Longer submissions are rejected outright, not truncated, so summarize rather than transcribe: short bullet-style statements of fact, not full sentences or pasted output.

Always read the status the call returns. A successful tool call does not by itself mean the summary was persisted:

- `stored` — written.
- `queued` — awaiting review; it is not in the vault yet.
- `duplicate` — an identical summary already exists; do not retry.
- `stored_without_project_link` — the summary was written, but its project cross-link matched an existing entry and was **not** written. The result carries `project_link_supersedes`; use `memory_supersede` with that ID if the link should be applied.

A rejected write is raised as an error, not returned. Never report a session as captured unless the status says it was.

## Pattern-linked memories

When a recurring situation may match a durable pattern, consult the current `/patterns.md` list. If a listed pattern matches, call `propose_pattern_match` with the pattern ID, a project fact, a global preference rule, and the stable project subject. The review queue decides whether first-occurrence generalizations are kept; later similar matches may be labeled confirmed patterns.

Both halves — the project fact and the preference rule — are validated before either is written, so a pattern is never half-stored. A rejected pattern is raised as an error naming the half that failed; correct that half and call again rather than retrying unchanged.


Writer identity for this client: `<tool-name>`.
