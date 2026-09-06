# Fix log

Each entry: what was wrong, what changed, where.

---

# 2026-09-06 — Tier 3 safety gate, patterns, and entity identity (branch `enhancements/roadmap`)

Ten issues, closing out tiers 3–4 and most of tier 5. Suite: 63 → 127 passing.

## #32 — Enhancement: normalize resilient lifecycle events without an HTTP hook dependency
Reused the useful lifecycle-hook patterns from an external reference project (stable
event names, fail-open behavior, bounded delivery, retry awareness) inside the existing
local SQLite receiver, without adopting its HTTP server architecture or enabling prompt
capture implicitly. Additive SQLite migration for buffers created by earlier versions.

## #16, #28, #18 — Pattern-linked memories: config, boundary fix, and historical backfill
`scripts/backfill_patterns.py` previously drove `MemoryManager` in-process and called the
private `_patterns()`, bypassing the configured write mode (#21's boundary) and lacking
`--dry-run`. Rewired to submit through the public MCP tool (`memory_hub.mcp_server.
memory_propose`) and read patterns through `memory_hub/patterns.py`'s supported loader.
`tests/test_mcp_server.py::McpBoundaryTests` now asserts no exemption for this script.
Tests: `tests/test_patterns.py`, `tests/test_backfill_patterns.py`.

## #33 — Bug: project memory identity allowed duplicate-looking entries across writers
Explicit `entity_id` + `aliases` frontmatter for project files, resolved through
`Vault._entity_slug()` (then `_project_slug()`) rather than fuzzy text matching. Added
`project_audit()` (read-only: exact duplicates, alias collisions, possible name splits)
and `project_link()` (explicit, reversible merge with a `.merged-<timestamp>` backup).
Tests: `tests/test_manager.py` project-identity and audit cases.

## #37 — Bug: project writes without entity_id could silently merge through prefix fallback
`_project_slug()`'s legacy hyphen-prefix fallback (kept for backward compatibility when
#33 landed) still let `widget-app-ui` route into an existing `widget-app.md` file with no
`entity_id` supplied and no confirmation. Removed the fallback entirely: a write that
omits `entity_id` now always gets its own subject-based file, never a fuzzy-matched
existing one. `project_audit()`/`subject_audit()` report the relationship for explicit
review instead.

## #29 — Enhancement: vault history as undo, plus hook install and uninstall
Part 1 (opt-in vault Git history, `history-init`/`history-status`/`history-commit`) and
the generic `memory_hub/hooks.py` layer (`install_hook`/`uninstall_hook`, timestamped
backups, managed-entry-only removal) were already implemented, but nothing called them —
`connect-ai-tools.ps1` exposed only `-VaultPath`/`-WriteMode`. Added `-InstallHooks`/
`-RemoveHooks`, targeting Claude Code's `settings.json` (resolved from
`$CLAUDE_CONFIG_DIR`, falling back to `~/.claude`) and pointing the hook command at the
venv's own `ai-memory-hook.exe` rather than trusting `PATH`. Verified live against a temp
`settings.json`: fresh install, idempotent repeat, removal preserving an unrelated
existing hook, safe no-op on a second removal, and a backup on each mutating write.

## #36 — Bug: rejected session_write/propose_pattern_match lost their reason
Both raised a plain `ValueError` on rejection. The MCP SDK (`mcp` 2.x) treats any
exception that is not `ToolError`/`ResourceError`/`MCPError` as a crash and wraps it in
`UnexpectedToolError`, discarding the original message — the caller saw only
`Error executing tool <name>`. Confirmed live (a too-long `session_write` payload lost its
"memory is too long" reason entirely) and against the SDK source
(`mcp/server/mcpserver/tools/base.py`). Fixed by raising `ToolError` instead, the SDK's
"anticipated failure" channel, whose message survives the same wrapping. Also documented
the 1500-character combined-section cap in `client-prompts/generic.md` (undiscoverable
before except by hitting it), synced to all eight client files.
Tests: `tests/test_mcp_server.py`, asserting through the real `mcp.call_tool()` boundary
rather than the bare function, since that is where the bug actually lived.

## #34 — Enhancement: generalize memory audit to detect subject sprawl across all kinds
`project_audit()` only ever looked at `kind == "project"` (one hardcoded filter). Added
`subject_audit(kinds=None)`, generalizing exact-duplicate detection (partitioned by
`(kind, hash)`, so identical text under different kinds is correctly not a duplicate of
itself) and subject-variant/file-split candidates to every kind, with `session` excluded
from the variant checks (its subjects are per-instance, not entity names). Run live
against the author's real vault (49 records): found the already-known project split plus
a previously invisible preference-kind variant.
Tests: `tests/test_manager.py::SubjectAuditTests` (9 new).

## #35 — Enhancement: extend entity identity to preferences/topics, group in dashboard
Two different mechanisms. `topic`/`decision`/`person` already routed one file per subject
like `project`; widened the same frontmatter gate and `_entity_slug()` routing to cover
them (mechanical, low-risk, reusing #33's tested code path). `preference`/`profile` route
every subject into *one* file across all subjects, so the same frontmatter mechanism
would have given the whole file one entity id shared across unrelated concerns — built a
separate registry instead, `entity-aliases.md` (`memory_hub/entities.py`), consulted by
`conflicts()`/`resolve_conflict()` and new `entity_alias_link()` (preview/apply, never
merges or deletes an entry). Dashboard grouping moved server-side into
`dashboard._dashboard_group()`, resolving preference/profile subjects through the same
registry; verified live against a disposable copy of the author's real vault (server
started, `GET /api/memories` returned all 49 rows with the new grouping fields).
Caught and fixed one bug pre-ship: the registry's own seed documentation embedded its
format example as a literal heading, which the (deliberately Markdown-fencing-naive)
parser would have read as live data on every new vault.
Tests: `tests/test_entities.py`, `tests/test_manager.py::FileEntityIdentityTests` and
`::EntityAliasLinkTests` (24 new total), one new dashboard grouping test; one stale
literal-string dashboard test updated rather than reverted.

---

# 2026-09-06 — Tiers 0–2 (branch `enhancements/roadmap`)

Nine issues, in the tier order recorded in roadmap #13. Five of them (#22–#25,
#28) came out of a code review of this branch and were reproduced before being
filed. Suite: 37 → 63 passing, 1 expected failure.

## #26 — Decision: session routing was writer-major, which hook capture would not survive
`memory_hub/vault.py` `canonical_path()`: takes a keyword-only `project` and
returns `/sessions/<project>/<model>.md` when one is named; sessions naming no
project stay at `/sessions/<model>.md`. Hook capture is per-working-directory,
so the old layout would have grown one unbounded file per agent spanning every
project. Project slugs reuse `_merge_into_existing_project()` so sessions and
`/projects/` cannot disagree on naming.
`scripts/migrate_session_routing.py`: relocates existing blocks, keyed on each
block's `**Project:**` link. `--dry-run`, idempotent, preserves IDs and
frontmatter, skips ID-less blocks (#24).
Tests: `tests/test_sessions.py::SessionRoutingMigrationTests` (6),
`test_session_without_project_stays_writer_major`,
`test_sessions_for_two_projects_are_separate_files`.

## #20 — Bug: memory_forget could not delete session summaries
`memory_hub/vault.py`: added `delete_session_block()`, which finds the `##`
block carrying `<!-- session:<id> -->` and rebuilds the file from its parsed
frontmatter plus surviving blocks. `manager.forget()` dispatches on record
kind. Previously it always called `delete_entry()`, whose `ENTRY_RE` line scan
cannot match a heading block, so every session deletion returned
`not_found_in_file` while the block stayed in the vault.
Tests: `tests/test_sessions.py` — deletion, sibling/frontmatter survival,
missing ID, and non-session deletion still working.

## #24 — Bug: session blocks that lost their ID marker were invisible, and audit called the vault healthy
`memory_hub/vault.py`: added `orphan_session_blocks()`. `manager.audit()` runs
it over files whose frontmatter `type` is `session`, reports them under
`orphan_session_blocks`, and counts them in `healthy`. `parse_records()` skips
such blocks, and `audit()` previously only checked index-vs-file drift and
malformed `- [` lines, so an orphan matched neither side of the reconciliation.
Tests: `test_audit_reports_session_block_without_id_marker`,
`test_audit_healthy_for_intact_session_file`.

## #25 — Bug: identical session summaries were stored twice
`memory_hub/manager.py`: added `_duplicate_session()`, checked before both the
review-mode enqueue and the auto-mode write. `propose_session()` never called
any duplicate detection at all. Keyed on **writer + title + body hash**, not on
date: `session_write` stamps `now` when a client omits `session_date`, so a
retry after a transport timeout carries a different date than the call it
repeats, and a date-inclusive key would miss exactly the case this exists for.
Tests: `test_identical_session_resubmission_is_a_duplicate`,
`test_retry_without_explicit_date_is_still_a_duplicate`,
`test_distinct_sessions_with_same_title_are_both_stored`.

## #22 — Bug: session project cross-links were dropped silently
`memory_hub/manager.py` `propose_session()`: when the linked project write
returns `possible_update` — a near-match that writes nothing — the result is
now `stored_without_project_link`, carrying `project_link_supersedes` and a
hint pointing at `supersede()`. Previously the session's own `stored` status
was returned regardless, so cross-links vanished with no signal. `approve()`
was updated in the same change: it keyed on the literal string `"stored"`, so
an approved session with a dropped cross-link would otherwise have been left
in the queue under the new status.
Tests: `test_dropped_project_cross_link_is_reported`,
`test_successful_cross_link_still_reports_stored`.

## #23 — Bug: pattern dual-write was not atomic and its rejection was swallowed
`memory_hub/manager.py` `propose_pattern_match()`: both candidates are built
and validated before either is written, so a half that cannot be stored stops
the pair before anything is committed. Rejections propagate `reason` (formerly
dropped, leaving `reason: None`) and add `half` naming the failing side.
`memory_hub/mcp_server.py`: the tool raises `ValueError` on rejection, matching
`session_write`'s contract since #12.
Tests: `tests/test_patterns.py` (3 new), `tests/test_mcp_server.py` (2 new).

## #19 / #21 / #12 — write mode, the client boundary, and validation
Behavior was already correct; what was missing was proof and documentation.
`ARCHITECTURE.md` (new) records the public-MCP-tool boundary with a tool →
internal-method table, the write-mode policy, the six write outcomes, pattern
atomicity, session routing, and the rejected HTTP/Node capture draft (#30).
`tests/test_mcp_server.py::McpBoundaryTests` parses client scripts with `ast`
and asserts none imports `memory_hub.manager`. It is marked
`@unittest.expectedFailure` for the one known violation,
`scripts/backfill_patterns.py` (#28, tier 4) — when that is fixed the test
flips to unexpected success and forces the marker's removal.
Tests: `test_review_mode_writes_nothing_to_the_vault`,
`test_auto_and_review_modes_differ_on_identical_input`.

---

# Fix log — 2026-09-05

Fixes for all 8 open issues at github.com/vib28/ai-memory-hub/issues, applied
most-to-least important.

## #2 — SECURITY: target_path let any client write into AI_INSTRUCTIONS.md / MEMORY.md
`memory_hub/vault.py`: added `RESERVED_FILENAMES = {"memory.md", "ai_instructions.md"}`.
`memory_hub/manager.py` `propose()`: reject any `target_path` whose basename
(case-insensitive) is one of those, before the write happens. No connected
client (Claude, Codex, Gemini, Kimi, ChatGPT, Hermes, ...) can plant
instructions into the files every other tool trusts.
Test: `tests/test_manager.py::test_reserved_target_path_is_rejected`.

## #6 — SECURITY: dashboard had no Origin/Host check
`memory_hub/dashboard.py`: `DashboardHandler` now carries a random per-launch
`launch_token` (generated in `serve()`) and an `allowed_hosts` set. Every
`do_POST` request is checked (`_origin_ok()`) against the `Host` header, the
`Origin` header when present, and an `X-Launch-Token` header the page must
echo back — the dashboard's own JS embeds the token via a template
substitution in `do_GET`'s HTML response. Requests failing any check get a
403 before the manager is touched. Defeats DNS rebinding and cross-origin
`no-cors` POSTs, since an attacker page can't know the launch token.
Tests: `tests/test_dashboard_features.py::DashboardOriginProtectionTests`.

## #5 — Bug: file_lock wrote a PID nobody read, so a crash caused a permanent deadlock
`memory_hub/utils.py` `file_lock()`: on `FileExistsError`, the lock's PID is
now read back (`_read_lock_pid`) and checked for liveness (`_pid_alive` —
`os.kill(pid, 0)` on POSIX, `OpenProcess`/`GetExitCodeProcess` on Windows,
since `os.kill(pid, 0)` is not a safe existence check there). A lock left by
a dead process is unlinked and the wait continues instead of hitting the
timeout and staying stuck forever.
Test: `tests/test_utils.py::StaleLockTests::test_lock_from_dead_pid_is_stolen_not_timed_out`.

## #7 — Race: ensure_file wrote the skeleton before append_entry took the lock
`memory_hub/vault.py` `append_entry()`: file creation (mkdir + skeleton
write) now happens *inside* the same `file_lock` critical section as the
append, instead of via a separate unlocked `ensure_file()` call beforehand.
Two writers racing on a brand-new file can no longer each write their own
skeleton and clobber one another. The now-unused `ensure_file()` helper was
removed rather than left as a dangling unlocked entry point.

## #4 — Bug: payment-card regex fired on any 13-19 digit run
`memory_hub/security.py`: replaced the blanket `\d[ -]*?){13,19}` pattern
with a candidate regex that only allows separators every 4 digits (real card
formatting) plus a Luhn checksum (`_luhn_ok`) before flagging anything as a
"possible payment/account number". Internal IDs, SAP ranges, and arbitrary
digit runs pass through (~9/10 chance of failing Luhn); real-looking card
numbers still get caught.
Tests: `tests/test_security.py` (SAP range, ID list, real Visa test number, API key still flagged).

## #3 — Correctness: near-duplicate at 0.93 silently dropped wanted updates
`memory_hub/manager.py`: split the single 0.93 threshold into
`TRUE_DUPLICATE_THRESHOLD = 0.985` (hard-blocked as a genuine duplicate) and
`DUPLICATE_UPDATE_BAND = 0.85` (close but not identical — same subject, one
token different). `propose()` now returns `status: "possible_update"` with
the matching memory instead of silently discarding it, so a caller can
resolve it via `supersede()`. `queue()` similarly returns
`status: "queued_as_update"` with `supersedes_id` pre-filled, so approving it
from the review queue applies as an update rather than getting rejected as a
dup a second time. As a secondary fix, the `SequenceMatcher` scan is now
filtered to same-kind rows only, cutting the comparison set instead of
scanning the whole index on every proposal.
Test: `tests/test_manager.py::test_near_duplicate_update_is_surfaced_not_silently_dropped`.

## #8 — CI: no GitHub Actions workflow; thin test coverage
Added `.github/workflows/ci.yml` (Ubuntu + Windows, Python 3.10-3.12,
`pytest` on push/PR). Added `tests/test_security.py` and `tests/test_utils.py`
covering the specific high-risk paths called out in the issue: SECRET_PATTERNS
hits/misses including the card regex, `safe_join` traversal/backslash/absolute-path
escapes, and the stale-lock concurrency case. `test_manager.py` gained reserved-file
and near-duplicate-update coverage. (Full concurrent-writer race coverage and a
coverage-upload step were left out as lower value for the time spent — the workflow
and the specific security/lock paths were the concrete ask.)

## #9 — Chore: remove leftover plan.md
Removed `plan.md` from the repo root via `git rm`.

---
All 26 tests pass locally (`python -m unittest discover -s tests`).
Not yet pushed/closed on GitHub — left for explicit confirmation before
touching the shared repo/issue tracker.
