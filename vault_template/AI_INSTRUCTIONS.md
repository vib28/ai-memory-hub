# AI Memory Protocol

This vault is the canonical persistent memory shared by authorized AI tools.

## Session retrieval

1. Read `/MEMORY.md` first when personal context is relevant.
2. Open only files whose index descriptions bear on the current request.
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
- `[inferred]` only when explicitly permitted
- `[superseded]` historical only

Every stored entry receives a stable memory ID and provenance.

Example:

```markdown
- [preference] Prefers concise answers first. <!-- mem:abc123 source:chatgpt date:2026-09-04 -->
```

## Updating

- Read the current file immediately before editing.
- Never bulk-overwrite a memory file.
- Preserve unfamiliar lines and other tools' contributions.
- Newer explicit user statements supersede older conflicting facts.
- Use `memory_supersede` when the old memory ID is known.

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
