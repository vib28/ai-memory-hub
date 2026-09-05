# Documentation and memory-protocol update plan

## Objective

Bring the public documentation, installed client instructions, and fresh-vault template into alignment with the recent conflict-detection, project-routing, timestamp, and dashboard changes. Do not change user vaults; only project-distributed files are in scope.

## Findings from the review

- The README feature list and dashboard overview already cover the four headline changes introduced in `4af5634` and `73675cb`.
- The detailed memory-format example still shows a date-only entry stamp, whereas newly created and edited entries now use a local second-precision timestamp. Date-only legacy entries remain valid.
- The README says the dashboard can “force a reindex,” but the current dashboard exposes audit only; reindex is available through the MCP/CLI surface, not the dashboard UI.
- The client prompts correctly require narrow retrieval and careful durable-memory proposals, but do not explain how to choose a stable `subject`. Consistent subjects are now important for singleton conflict detection and project-file routing.
- `vault_template/AI_INSTRUCTIONS.md` likewise needs the timestamp-compatible example and subject guidance so a freshly initialized vault has rules consistent with the server.
- Before making a strong public promise about conflict detection, verify a restart/reindex round trip: `parse_records()` currently derives `subject` from the file stem, so multiple independently scoped facts in `profile.md` or `preferences.md` can lose their original subjects after an index rebuild. This is a persistence limitation to resolve or explicitly constrain before finalizing the documentation.
- `qwen.md` identifies itself as `qwen`, but `ALLOWED_WRITERS` does not currently include `qwen`; validation normalizes unrecognized writers to `other`. Fix that provenance mismatch before asserting that every dedicated prompt preserves its named writer.
- Template files are copied only when missing during vault initialization. Updating `vault_template/` improves new vaults but does not retrofit existing vault instructions; the README should state the upgrade path if existing users need these guidance changes.

## Implementation plan

1. Establish a behavior baseline.
   - Run the existing unit suite.
   - Add focused regression coverage for full timestamps, hyphen-prefix project routing, singleton-only conflict detection, subject survival across reindex/restart, and every named client writer (including Qwen).
   - Add `qwen` to the accepted writer set (or deliberately change the Qwen prompt identity and docs); preserve the named writer is the expected behavior.
   - Use the result of the subject-survival test to choose the smallest safe fix: persist each entry’s subject in its metadata (while accepting existing entries without it), or narrow the documented conflict guarantee until that storage change is implemented.

1a. Verify the dashboard date and recency behavior before documenting it.
   - Create a new stored entry through the dashboard/API path and assert that its second-precision timestamp reaches the memory-list response and renders as a local date and time.
   - Keep ordinary date text visible on every card, but show the clock/recent badge only on the newest entry in each subject/project group. Do not label every entry as recent.
   - Cover date-only legacy entries and equal/nearby timestamp ordering so the most-recent marker is deterministic.

2. Correct and tighten `README.md`.
   - Update the memory-line example to show the supported ISO local timestamp form and state that legacy `YYYY-MM-DD` entries remain compatible.
   - Separate global deduplication from singleton-only conflict detection, so the current combined feature bullet cannot be read as limiting deduplication to profile/preferences.
   - Add concise routing guidance: exact project filenames win; otherwise either-direction hyphen-segment prefixes route to the shortest existing filename. Explain that an explicit `target_path` bypasses this routing and existing fragmented files are not consolidated automatically.
   - Correct the dashboard section to describe only available actions: forget requires confirmation, and reindex is available through MCP/CLI unless a dashboard control is intentionally added.
   - If the persistence regression is fixed, document that conflict matching uses a stable kind/subject pair; otherwise avoid overpromising that behavior across rebuilds.
   - Clarify that template updates seed new vaults only; give existing-vault users a small, non-destructive way to adopt the revised `AI_INSTRUCTIONS.md` guidance if it is needed.
   - Correct the arbitrary-writer statement to match validation (unknown writer IDs are normalized to `other`), and use the implementation’s singular kind names `profile` and `preference` in the routing table.

3. Update the distributed client prompts in `client-prompts/`.
   - Keep all tool-specific files semantically identical except for their writer identity.
   - Add a short proposal rule requiring a concise, stable, hyphenated `subject` for `memory_propose`/`memory_supersede` (for example, `primary-development-os`), and reuse the same subject for later updates of the same fact.
   - State that profile and preference subjects represent one current answer; use `memory_supersede` when a current explicit statement replaces one. Clarify that project, person, topic, and decision entries may accumulate distinct facts and should not be superseded merely because they share a subject.
   - Explain that a conflict candidate is a review signal rather than evidence that the newest fact is correct, and that queued proposals are not stored until approved in review mode.
   - Regenerate/copy the common prompt body carefully so no client loses its correct `Writer identity` line.

4. Update `vault_template/AI_INSTRUCTIONS.md` and the related seed files.
   - Add the same stable-subject and singleton-vs-log-kind guidance used by the client prompts.
   - Change the entry example to the timestamp-capable format, while noting old date-only stamps parse correctly.
   - Align the template’s inferred-memory wording with the server’s actual policy (inferred candidates are rejected), and state that connected clients should use MCP tools; retain `MEMORY.md` as a direct-file index fallback.
   - Preserve the template’s existing location, safety, update, and forgetting rules; no real vault content is changed.
   - Normalize the `MEMORY.md` preferences row type to `preference`. Leave `profile.md` and `preferences.md` otherwise minimal unless the selected subject-persistence design requires metadata changes.

5. Verify the shipped experience.
   - Run the complete tests, including the new restart/reindex cases.
   - Initialize a disposable vault from `vault_template`, confirm its instruction files and generated entry syntax are valid, then reindex and audit it.
   - Compare all seven client prompts to confirm only the writer identity differs.
   - Review the README commands and claims against the actual MCP, CLI, and dashboard endpoints.
   - After installing revised client prompts, reload each client’s instruction context: start a new Claude, Codex, Qwen, Gemini, or Kimi session; begin a new ChatGPT conversation after updating Custom Instructions; and restart/reload any manually configured MCP host. Existing sessions retain their already-loaded instruction context.

## Expected files

- `README.md`
- `client-prompts/chatgpt.md`
- `client-prompts/claude.md`
- `client-prompts/codex.md`
- `client-prompts/gemini.md`
- `client-prompts/generic.md`
- `client-prompts/kimi.md`
- `client-prompts/qwen.md`
- `vault_template/AI_INSTRUCTIONS.md`
- Potentially `memory_hub/vault.py`, `memory_hub/manager.py`, and focused tests, only if the reindex check confirms the subject-persistence defect.

## Out of scope

- Modifying any existing user vault or connector configuration.
- Rewriting unrelated installation, tunnel, or dashboard styling documentation.
