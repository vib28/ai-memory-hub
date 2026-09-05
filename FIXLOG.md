# Fix log — 2026-09-05

Fixes for all 8 open issues at github.com/vib28/ai-memory-hub/issues, applied
most-to-least important. Each entry: what was wrong, what changed, where.

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
