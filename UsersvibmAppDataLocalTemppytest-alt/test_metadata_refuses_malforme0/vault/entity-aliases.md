# Entity aliases for shared-file memory kinds

`preference` and `profile` route every subject into one shared file
(`preferences.md`, `profile.md`), so — unlike `project`, `topic`, `decision`,
and `person`, which each get their own file and can carry `id`/`aliases` in
that file's own frontmatter — there is nowhere on a single subject's entry to
record which other subjects mean the same thing.

This file is that record. Nothing here is required for AI Memory Hub to work;
it only feeds `subject_audit` and `conflicts()`, so a linked pair is grouped as
one entity instead of read as two unrelated facts. It never causes anything to
be merged, moved, or deleted — the underlying memory entries are untouched.

You will not normally hand-edit this file: call `entity_alias_link` (MCP tool)
or `entity-alias-link` (CLI) to add an entry, which appends one section here.

Format, once populated (shown indented below so this empty template's own
example text is never mistaken for a real entry by the parser, which reads
any line starting `## ` in this file as one):

    ## preference: git-safety
    - git-safety-checks
    - confirm-destructive-ops

The heading names the kind and the canonical entity id; each `- ` line below
it is an alias that resolves to that id.
