# Fix log — 2026-09-19

Fixes applied across the `enhancements/auto-context-pipeline` branch, continuing
from the #2-#9 fixes on master. Each entry: what was wrong, what changed, where.

---

## #117 — Skip transcript re-render when unchanged — 2026-09-19

### #117 — Worker poll re-renders every transcript unconditionally
`memory_hub/worker.py`: the routine poll-driven re-render iterated ALL
transcript groups and called `render()` on every poll — even when neither
the events nor the resolved target had changed — churning the Markdown file
on every tick. Added a per-group content-hash watermark
(`self._transcript_watermarks: dict[str, str]`) keyed on the SHA-256 of the
event_id list and the resolved target (path/project/summary_links). The
fingerprint is computed before rendering; if it matches the last poll's
value, the render is skipped. `transcript_rendered` now only counts groups
that actually produced a new file. No per-append bookkeeping — the hash is
recomputed on each poll from the existing event set.

## Pipeline foundation (#82-#90, #91) — 2026-09-18

### #84 — Project resolver
`memory_hub/project_resolver.py`: turns a hook's `cwd` into one stable project
slug via vault override map -> `.ai-memory-project` pin -> nearest `.git`
(linked worktrees collapse onto the main repository) -> package marker -> leaf
name, with home/system/drive-root reserved as "unscoped". No git subprocess,
no network. 265-line module with 117-line test suite.

### #82 — Capture evidence
`memory_hub/capture.py`: preserves what hosts actually send — user prompt,
assistant final message, SessionStart source, SessionEnd reason, compaction
trigger, StopFailure error type, plus `transcript_path`/`model`/
`permission_mode`/`client_type` in a bounded `host_meta` column. Gemini and
Hermes event spellings normalize onto canonical events. Checkpoints route under
the evidence's client and carry the resolver's worktree. Verified against a
copy of the live 1,257-row buffer.

### #83/#87 — Detached worker
`memory_hub/worker.py` `run_once()`: hook receiver now spawns a detached
one-shot `worker --session <id> --force` child on session-end/stop events and
returns in milliseconds; the child outlives the host's hook timeout and writes
the checkpoint + manifest. StopFailure/Interrupt finalize as provisional final
so work stays continuable; heartbeats only refresh the idle clock. 314-line
process-level fixture covers hook -> detached worker -> manifest -> handoff
with no mocks between stages.

### #86 — Context injection
`memory_hub/context_packet.py` + `memory_hub/hooks.py`: context packets (start
+ turn) render the stdout contract each host documents. `connect-ai-tools
-InstallHandoff` wires all six hosts; `-InstallHooks` installs the full
lifecycle capture set and defaults session-auto on. 394-line context packet
module with 274-line test suite.

### #85 — Categorizer
`memory_hub/categorizer.py`: worker runs a model-free categorizer after each
checkpoint; candidates carry `evidence_ids` in `pending.provenance` and the
review queue displays them. 175-line module with 144-line test suite.

### #89 — MCP cwd parity
`memory_hub/mcp_server.py`: `memory_context` accepts `cwd` and returns the same
packet the hooks inject, closing the divergence between MCP and hook paths.

### #90 — Docs: pipeline is automatic
Docs no longer say capture stops short of unattended operation. All six hosts
(Claude, Codex, Gemini, Qwen, Kimi, Hermes) documented with full capture +
startup handoff.

### #88 — Test isolation / worker health leak
`tests/conftest.py`: scrubs `MEMORY_*`/`AI_MEMORY_*` env vars and redirects
`HOME` per test, fixing config-precedence test failures and stopping ~190
`worker-health-<hash>.json` files from landing in the developer's real
`~/.ai-memory-hub`. `worker_health_path` now defaults to
`<vault>/.ai-memory-hub/worker-health.json`.

### #91 — Priority order recorded
`docs/issue-priority-order.md`: #91 and children (#82-#90) lead the order;
#61/#62 follow because the benchmark cannot measure a pipeline that does not
run.

---

## Security & efficiency fixes (ultrareview) — 2026-09-19

### #92 — CRITICAL: worker forwarded all env to child subprocesses
`memory_hub/worker.py`: detached consolidation children now receive only an
allowlisted set (`AI_MEMORY_VAULT`, `MEMORY_WRITER`, `MEMORY_WRITE_MODE`, `PATH`,
`HOME`, `USERPROFILE`) instead of the full `os.environ`.

### #94 — CRITICAL: capture persisted secrets to the buffer DB
`memory_hub/capture.py`: new `_sanitize_payload()` redacts sensitive fields
BEFORE any SQLite write. `hook_main()` sanitizes payloads before both buffer
append and transcript append. 68 new regression tests.

### #96/#98/#104/#106 — HIGH priority dedup/perf
`memory_hub/context_packet.py`: caches index rows by vault mtime, uses
`resolve_project_cached`, pre-computes token sets per row to avoid O(N) regex
passes per prompt. `worker.py`: single aggregate query instead of N+1 for
backlog. `utils.py`: extracted `one_line`, `is_truthy`, `parse_iso_datetime`
as single-source helpers, removing duplicated definitions across 3+ files.
342 tests pass.

### Kimi context filtering
`memory_hub/context_packet.py`: expanded `_STOPWORDS` to cover common verbs,
added `_MIN_CONTENT_TOKEN_LEN` filter (short tokens excluded unless paired
with longer content), and added a score floor (0.3) so Kimi-style full-trace
prompts no longer match embedding/business memories. Regression tests verify
legitimate prompts still match relevant memories.

---

## 15-defect remediation (#67-#81) — 2026-09-09

Report-the-truth defects (a call claimed success without the side effect):

- **#67** `hooks.py`: Codex hook uninstall never removed a handler alone in its
  group, though `install_codex_hook` always creates exactly that shape.
- **#69** `mcp_server.py`: `session_consolidate` raised `AttributeError` on any
  project-less session with vault history enabled.
- **#72** `worker.py`: a degraded run erased the previously recorded
  `last_success_at`, making "failing for a minute" indistinguishable from
  "never succeeded".
- **#75** `handoff.py`/`github_export.py`: malformed `MEMORY_*` integer env var
  crashed argparse construction outside the graceful-degradation try block.
  Promoted the existing safe helper into shared `memory_hub/_env.py`.

Transcript path/link unification (#68, #70):

- `manager.py`: added `MemoryManager.session_transcript_target()` as the single
  resolver for a group's transcript path/project/summary-links, read from the
  session manifest. `worker.py` and `session_capture.py` now call it,
  eliminating silent summary back-link stripping every 15 seconds.

Transcript store (#66, #76, #77):

- `transcript.py`: `delete_group` now enumerates the group's distinct projects
  before deleting rows and removes every candidate path, not only the unscoped
  default.
- Added `generated_at_source` column and inline "not supplied by provider"
  marker in rendered Markdown.

Worker idle trigger (#71):

- `worker.py`: idle now checked before flush and measured from the newest
  pending row, not the oldest. With shipped defaults (`flush_seconds=60 <
  idle_seconds=300`) the old ordering meant idle could never fire —
  `MEMORY_WORKER_IDLE_SECONDS` was dead configuration.

GitHub exporter (#73, #74):

- `github_export.py`: `find_issue`/`list_comments` now page through every result
  via `gh api --paginate --slurp`. `ExportOutbox.claim_group` returns only the
  rows it just locked instead of the whole group, eliminating unbounded per-poll
  write cost.

Index (#78, #79):

- `index.py`: `_embed_record` now computes new vectors before deleting the old
  ones, so a transient outage leaves a record's existing vectors in place.
  Takes `manage_transaction`, threaded through from `upsert(commit=...)`, so
  `rebuild()`'s per-record embed step no longer opens its own nested
  `with self.conn` and commits the caller's outer transaction early.

Vault (#80):

- `vault.py`: `update_session_metadata` and `delete_session_block` now preserve
  content above the first `## ` session heading instead of dropping it on
  rewrite — `_complete_checkpoint_links` calls `update_session_metadata` on
  every checkpoint, so this was routine data loss.

Dashboard/config hardcoding (#81):

- `dashboard.py`: added `MEMORY_DASHBOARD_PORT`/`MEMORY_DASHBOARD_HOST` as the
  single source of the port/host default, used by `app.py`, `dashboard.py` and
  all three `*.ps1` launchers instead of six independently hardcoded `8765`s.
- `connect-ai-tools.ps1`: `Get-GeminiSettingsPath`/`Get-QwenSettingsPath` now
  honor `GEMINI_CONFIG_DIR`/`QWEN_CONFIG_DIR`, matching the existing
  `KIMI_CONFIG_DIR` pattern.

36 new regression tests, one per fix. 252 tests pass (up from 216).

---

## Config file settings & dashboard redesign — 2026-09-09

### Config-file settings (`memory_hub/app_config.py`)
Replaces a broken WinForms configuration script (TabControl never rendered a
tab strip) with configuration folded into the browser dashboard, backed by a
real JSON config file. `SETTINGS_SCHEMA` is the single source of truth for
every setting's key, group, type, default, min/max or options — both the
dashboard API and frontend form render from it. `bootstrap_environment(vault)`
seeds `os.environ` from `<vault>/.ai-memory-hub/config.json` using `setdefault`
semantics: explicit env vars always win. `effective_config()` reports each
setting's current value and whether it came from file, env, or built-in
default. `save_settings()` validates against the schema and merges into the
existing file.

### Dashboard Settings pane
New Settings view renders grouped cards from the schema with per-field source
badge (DEFAULT/ENV/FILE). Only fields the user actually edits get submitted on
save, so a field showing an env-sourced value never gets silently baked into
the file. `app.css` rewritten with a single `--accent` token, distinct serif
reading-pane typography, and WCAG-verified contrast across all four palettes
(light/dark/colorblind-light/colorblind-dark).

269 tests pass (up from 252; 17 new in `tests/test_app_config.py` and
`tests/test_dashboard_redesign.py`). Verified live in a real Chrome tab.

---

# Fix log — 2026-09-05 (master)

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