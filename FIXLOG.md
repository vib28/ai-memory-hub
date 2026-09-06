# Fix log

Each entry: what was wrong, what changed, where.

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
