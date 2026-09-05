# AI Memory Protocol

This vault is the canonical persistent memory shared by authorized AI tools.

## Session retrieval

1. For a connected client, use `memory_search` first and `memory_read` only for a clearly relevant file.
2. For direct-file use, read `/MEMORY.md` as the index, then open only files whose descriptions bear on the request.
3. Never scan the entire vault by default.
4. Never ask the user to repeat information already present in relevant memory.
5. Current explicit user statements override older stored facts.

## Automatic writes

The user does **not** need to say "remember this."

Automatically store only high-confidence information that is:

- durable for weeks/months
- user-specific
- future-useful
- non-sensitive
- clearly canonical
- not already stored

Prefer session-end/boundary batch proposals rather than writing after every message.

Good:
- stable identity, role, stack, timezone
- durable response/workflow preferences
- important purchases affecting future recommendations
- ongoing project objectives and constraints
- explicit decisions
- recurring interests/preferences
- unresolved questions that materially affect ongoing work

Do not auto-store:
- secrets, passwords, API keys, tokens, seed phrases, IDs, credentials
- current prices/search results/news
- generated code or assistant suggestions
- transient bugs/errors/errands
- temporary moods
- uncertain plans
- speculative inferences
- sensitive inferred personal attributes

## Entry semantics

Allowed tags:
- `[stated]`
- `[decided]`
- `[preference]`
- `[constraint]`
- `[open]`
- `[superseded]` historical only

Every stored entry receives a stable memory ID and provenance.

Use a concise, stable, hyphenated subject for each fact and reuse it for later updates. A `profile` or `preference` subject represents one current answer; supersede an entry only when an explicit statement replaces it. `project`, `person`, `topic`, and `decision` are cumulative logs, so distinct facts may share a subject. Treat a detected conflict as a review signal, not evidence that the most recent entry is correct.

Example:

```markdown
- [preference] Prefers concise answers first. <!-- mem:abc123 source:chatgpt subject:response-style date:2026-09-04T14:30:00 -->
```

New and edited entries use a local timestamp with second precision. Legacy date-only entries remain valid. `inferred` candidates are rejected by the server.

## Updating

- Read the current file immediately before editing.
- Never bulk-overwrite a memory file.
- Preserve unfamiliar lines and other tools' contributions.
- Newer explicit user statements supersede older conflicting facts.
- Use `memory_supersede` when the old memory ID is known.
- In review mode, a proposed memory is stored only after approval.

## Canonical location

- stable identity -> `/profile.md`
- AI/workflow preference -> `/preferences.md`
- person -> `/people/<slug>.md`
- project -> `/projects/<slug>.md`
- recurring domain -> `/topics/<slug>.md`
- cross-project decision -> `/decisions/<slug>.md`

One fact should have one canonical home. Use wikilinks rather than duplicating facts.

## Forgetting

Explicit user requests to forget information override normal history preservation.
Delete the requested memory and do not retain its substance merely for provenance.

## Golden tests

Before storing:
"Will this materially improve a future AI response a month from now?"

Before reading:
"What is the smallest amount of memory required to answer well?"
