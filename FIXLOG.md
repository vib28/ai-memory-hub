# Fix Log — auto-context-pipeline

Fixes applied across the `enhancements/auto-context-pipeline` branch, continuing
from the #2-#9 fixes on master. Organized by priority.

---

## CRITICAL Fixes

| # | Issue | Summary | Where | Tests |
|---|-------|---------|-------|-------|
| #92 | Worker forwarded ALL `os.environ` to child subprocesses | Allowlisted env vars only | `memory_hub/worker.py` | 68 |
| #94 | Capture persisted secrets to the buffer DB | Redact sensitive fields before SQLite write | `memory_hub/capture.py` | 68 |
| #119 | SQLite cross-thread access corruption | Added `threading.RLock` around all SQLite ops | `memory_hub/index.py` | 343 |
| #120 | Dashboard leaked exception details to client | Log full exception server-side, return generic message | `memory_hub/dashboard.py` | 343 |
| #146 | `extract_candidates` undefined | Replace with `extract_from_transcript` | `memory_hub/cli.py` | 343 |

---

## HIGH Fixes

| # | Issue | Summary | Where |
|---|-------|---------|-------|
| #96 | Context packet O(N) regex per prompt | Cache index rows by mtime, pre-compute token sets | `memory_hub/context_packet.py` |
| #98 | N+1 query for backlog | Single aggregate query | `memory_hub/worker.py` |
| #100 | 120 lines of copy-paste in hook install/uninstall | Shared `_install_managed_hook` / `_uninstall_managed_hook` | `memory_hub/hooks.py` |
| #104 | Duplicated helpers across 3+ files | Extract to `utils.py` | `memory_hub/utils.py` |
| #106 | Duplicated timestamp parsers in 4 files | Single `parse_iso_datetime` in `utils.py` | `memory_hub/utils.py` |
| #108 | Health JSON written on every poll | Skip redundant writes, dedup identical payloads | `memory_hub/worker.py` |
| #110 | 18 per-client hook functions in PowerShell | Client registry + 4 generic functions | `connect-ai-tools.ps1` |
| #112 | MCP module-side effects | Lazy init via `_ensure_init()` | `memory_hub/mcp_server.py` |
| #115 | Dashboard class-level RLock serialized all requests | Removed lock, per-handler threading | `memory_hub/dashboard.py` |
| #116 | No token check on sensitive GET endpoints | Require `X-Launch-Token` | `memory_hub/dashboard.py` |
| #117 | Transcript re-rendered on every poll | SHA watermark, skip unchanged | `memory_hub/worker.py` |
| #121 | `_covers_cache` never invalidated | Auto-invalidate on write | `memory_hub/manager.py` |
| #122 | Hot hook path used uncached `resolve_project` | Use `resolve_project_cached` | `memory_hub/context_packet.py` |
| #123 | Dashboard fetched `all_rows()` twice | Fetch once, reuse twice | `memory_hub/dashboard.py` |
| #124 | `entity_registry` re-read every call | Cache by file mtime/size | `memory_hub/manager.py` |
| #125 | Capture status updates executed one-by-one | Batch with `IN` + `executemany` | `memory_hub/capture.py` |
| #126 | Worker re-read manifest on every `run_once` | Cache manifest per pass | `memory_hub/worker.py` |
| #127 | Silent exception in `bootstrap_environment` | Log with full traceback | `memory_hub/app_config.py` |
| #128 | Silent transcript errors | Log with full tracebacks | `memory_hub/worker.py` |
| #129 | Silent packet build errors | Log with logger | `memory_hub/context_packet.py` |
| #147 | `uninstall_nested_hook` matched wrong handler | Exact command matching | `memory_hub/hooks.py` |
| #148 | Embeddings lookup scanned entire index | Restrict to candidates only | `memory_hub/index.py` |
| #149 | `context_prime` re-read all rows | Cache `all_rows()` | `memory_hub/manager.py` |
| #150 | `_covers_cache` stale after writes | Invalidate after every write | `memory_hub/manager.py` |
| #151 | `events()` query ran even when watermark matched | Skip query when no change | `memory_hub/worker.py` |
| #152 | FTS5 double-quote injection | Escape double quotes in queries | `memory_hub/index.py` |
| #174 | Unbounded `response.read()` in consolidator | Cap read size | `memory_hub/consolidator.py` |
| #175 | Unbounded `response.read()` in embeddings | Cap read size | `memory_hub/embeddings.py` |
| #176 | Unbounded `response.read()` in extractor | Cap read size | `memory_hub/extractor.py` |
| #205 | Exception str leaked in JSON response | Sanitize exc str | `memory_hub/capture.py` |
| #206 | Unlocked `_read_index_rows` cache | `threading.Lock` | `memory_hub/context_packet.py` |
| #207 | `_safe_set_status` unbounded retry | Bounded retry with cap | `memory_hub/manager.py` |

---

## MEDIUM Fixes

| # | Issue | Summary | Where |
|---|-------|---------|-------|
| #67 | Codex hook uninstall never removed lone handler | Handle single-handler case | `memory_hub/hooks.py` |
| #69 | `session_consolidate` `AttributeError` on project-less sessions | Guard against missing project | `memory_hub/mcp_server.py` |
| #72 | Degraded run erased `last_success_at` | Preserve last success timestamp | `memory_hub/worker.py` |
| #75 | Malformed `MEMORY_*` env var crashed argparse | Safe helper in `memory_hub/_env.py` | `memory_hub/handoff.py` |
| #88 | Test config leaked into real `~/.ai-memory-hub` | Scrub env + redirect HOME per test | `tests/conftest.py` |
| #133 | Dead code clause in `_tokens` | Remove unreachable branch | `memory_hub/context_packet.py` |
| #153 | Constants duplicated across modules | Single source in `events.py` | `memory_hub/events.py` |
| #154 | `read_json` duplicated in multiple files | Single helper in `utils.py` | `memory_hub/utils.py` |
| #155 | `vault_key` duplicated | Single helper in `utils.py` | `memory_hub/utils.py` |
| #156 | `one_line` duplicated | Single helper in `utils.py` | `memory_hub/utils.py` |
| #157 | `truncated_text` duplicated | Single helper in `utils.py` | `memory_hub/utils.py` |
| #158 | `atomic_write` duplicated | Single helper in `utils.py` | `memory_hub/utils.py` |
| #159 | Hook constants scattered | Consolidate in `events.py` | `memory_hub/events.py` |
| #160 | GitHub exporter used naive datetime | tz-aware datetime | `memory_hub/github_export.py` |
| #161 | `context_prime` exceptions swallowed | Log exceptions | `memory_hub/manager.py` |
| #162 | Categorizer missing `evidence_ids` | Pass `evidence_ids` to constructor | `memory_hub/categorizer.py` |
| #163 | `SESSION_SECTIONS` redefined per call | Module-level constant | `memory_hub/manager.py` |
| #164 | `subject_audit_file_splits` O(n²) | Adjacent-pairs algorithm | `memory_hub/manager.py` |
| #165 | Vault temp files world-readable | `chmod 0o600`; cache `entity_slug` | `memory_hub/vault.py` |
| #166 | Dashboard memories unordered | `ORDER BY` DESC | `memory_hub/dashboard.py` |
| #167 | Orphan + malformed scans duplicated | Merge into single pass | `memory_hub/manager.py` |
| #168 | `cosine_similarity` multi-pass | Single-pass implementation | `memory_hub/embeddings.py` |
| #169 | `atomic_write` world-readable temp | `chmod 0o600` in `atomic_write` | `memory_hub/utils.py` |
| #170 | Dashboard missing security headers | Add CSP, X-Frame-Options, etc. | `memory_hub/dashboard.py` |
| #171 | Capture status update non-atomic | Atomic `UPDATE ... RETURNING` | `memory_hub/capture.py` |
| #172 | Models used `Optional[str]` | `str \| None` (PEP 604) | `memory_hub/models.py` |
| #173 | CLI didn't set `evidence_ids` from transcript | Set from transcript hash | `memory_hub/cli.py` |
| #177 | `_entity_slug` cache no-op | Fix cache logic | `memory_hub/manager.py` |
| #178 | Dashboard HTML re-built per request | Module-level HTML constant | `memory_hub/dashboard.py` |
| #179 | `audit()` double file-read | Read once, reuse | `memory_hub/manager.py` |
| #180 | `propose_session` double manifest read | Read once, reuse | `memory_hub/manager.py` |
| #181 | `search()` fetched entire index | Fetch only candidates | `memory_hub/index.py` |
| #182 | `assert` used for validation | Explicit `raise` | `memory_hub/manager.py` |
| #183 | `session_write` used raw dict | `SessionCheckpoint` dataclass | `memory_hub/mcp_server.py` |
| #184 | `_ensure_init()` race condition | `threading.Lock` | `memory_hub/mcp_server.py` |
| #185 | Silent exceptions in 4 modules | Add debug logging | multiple |
| #186 | Missing `return` in dashboard handler | Add missing return | `memory_hub/dashboard.py` |
| #187 | `_covers_cache` unlocked writes | `threading.Lock` | `memory_hub/manager.py` |
| #188 | `safe_join` duplicated in handoff/github_export | Consolidate in `utils.py` | `memory_hub/utils.py` |
| #189 | GitHub export didn't sanitize secrets | `sanitize_secrets` helper | `memory_hub/github_export.py` |
| #190 | `load_session_manifest` duplicated | Single helper in `handoff.py` | `memory_hub/handoff.py` |
| #191 | `to_kebab` duplicated | Single helper in `utils.py` | `memory_hub/utils.py` |

---

## LOW Fixes

| # | Issue | Summary | Where |
|---|-------|---------|-------|
| #192 | Dashboard `/api/memories` unpaginated | Add pagination | `memory_hub/dashboard.py` |
| #193 | GitHub export used raw string SQL | f-string parameterization | `memory_hub/github_export.py` |
| #194 | Index query inefficient | Targeted SQL with index | `memory_hub/index.py` |
| #195 | `_duplicate_session` scanned full table | Targeted SQL | `memory_hub/manager.py` |
| #196 | `memory_policy` missing `_ensure_init()` | Add lazy init | `memory_hub/mcp_server.py` |
| #197 | `utc_timestamp` redefined | Use shared helper | `memory_hub/utils.py` |
| #198 | `normalize_relative` redefined | Use shared helper | `memory_hub/utils.py` |
| #199 | `clean_one_liner` redefined | Use shared helper | `memory_hub/utils.py` |
| #200 | `context_packet` re-read index rows | Cache keyed on mtime | `memory_hub/context_packet.py` |
| #201 | Transcript minor cleanups | Cleanup | `memory_hub/transcript.py` |
| #208 | `packet_size` O(n²) | Running bytes counter | `memory_hub/context_packet.py` |
| #209 | `re.compile` called per invocation | Module-level cache | `memory_hub/context_packet.py` |
| #210 | `subject_audit` O(n²) | Adjacent-pair algorithm | `memory_hub/manager.py` |
| #211 | Broad `except` in extractor | Narrow to specific exceptions | `memory_hub/extractor.py` |
| #212 | Opaque `except` in github_export | Categorized exceptions | `memory_hub/github_export.py` |
| #213 | Mutable default args in cli/worker | `None` + init inside function | `memory_hub/cli.py`, `memory_hub/worker.py` |
| #214 | `datetime.now()` without timezone | tz-aware datetime | `memory_hub/hooks.py` |
| #215 | Missing `from __future__ import annotations` in tray | Add future annotations | `memory_hub/tray.py` |
| #216 | `utc_timestamp` not used where available | Use shared helper | `memory_hub/capture.py` |
| #217 | `vault_key` not used where available | Use shared helper | `memory_hub/github_export.py` |
| #218 | Helpers scattered across files | Consolidate | `memory_hub/utils.py` |
| #219 | MCP server module globals | Module-level variables | `memory_hub/mcp_server.py` |
| #220 | `type()` check instead of proper subclass | Subclass check | `memory_hub/dashboard.py` |
| #221 | Broad `except` in dashboard | Narrow to specific exceptions | `memory_hub/dashboard.py` |
| #222 | Broad `except` in capture | Narrow to specific exceptions | `memory_hub/capture.py` |
| #223 | `_tokens` recomputed per call | `lru_cache` | `memory_hub/context_packet.py` |
| #224 | `normalize_client` linear prefix scan | Index-based lookup | `memory_hub/capture.py` |
| #225 | `_best_match` recomputed per call | Normalized cache | `memory_hub/context_packet.py` |
| #226 | `__init__` missing future annotations | Add future annotations | `memory_hub/__init__.py` |
| #227 | `hooks.py` JSON reads unchecked | Safe JSON read | `memory_hub/hooks.py` |
| #228 | `manager.py` JSON reads unchecked | Safe JSON read | `memory_hub/manager.py` |

---

## 15-Defect Remediation (code-review pass — 2026-09-09)

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

## Config File Settings & Dashboard Redesign — 2026-09-09

**Config-file settings** (`memory_hub/app_config.py`):
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

**Dashboard Settings pane**:
New Settings view renders grouped cards from the schema with per-field source
badge (DEFAULT/ENV/FILE). Only fields the user actually edits get submitted on
save, so a field showing an env-sourced value never gets silently baked into
the file. `app.css` rewritten with a single `--accent` token, distinct serif
reading-pane typography, and WCAG-verified contrast across all four palettes
(light/dark/colorblind-light/colorblind-dark).

269 tests pass (up from 252; 17 new in `tests/test_app_config.py` and
`tests/test_dashboard_redesign.py`). Verified live in a real Chrome tab.

---

## Master Fixes (2026-09-05)

Fixes for all 8 open issues on master, applied most-to-least important.

| # | Priority | Summary | Where |
|---|----------|---------|-------|
| #2 | SECURITY | `target_path` let any client write into AI_INSTRUCTIONS.md / MEMORY.md | `memory_hub/vault.py`, `memory_hub/manager.py` |
| #6 | SECURITY | Dashboard had no Origin/Host check | `memory_hub/dashboard.py` |
| #5 | Bug | `file_lock` wrote a PID nobody read, crash caused permanent deadlock | `memory_hub/utils.py` |
| #7 | Race | `ensure_file` wrote skeleton before `append_entry` took the lock | `memory_hub/vault.py` |
| #4 | Bug | Payment-card regex fired on any 13-19 digit run | `memory_hub/security.py` |
| #3 | Correctness | Near-duplicate at 0.93 silently dropped wanted updates | `memory_hub/manager.py` |
| #8 | CI | No GitHub Actions workflow; thin test coverage | `.github/workflows/ci.yml`, `tests/` |
| #9 | Chore | Remove leftover `plan.md` | repo root |

All 26 tests pass locally.

---

## Pipeline Foundation (2026-09-18)

Core features that built the automatic context pipeline:

| Feature | Where | Tests |
|---------|-------|-------|
| Project resolver | `memory_hub/project_resolver.py` (265 lines) | 117 |
| Capture evidence | `memory_hub/capture.py` | Verified against 1,257-row buffer |
| Detached worker | `memory_hub/worker.py` | 314-line integration fixture |
| Context injection | `memory_hub/context_packet.py` + `memory_hub/hooks.py` (394 lines) | 274 |
| Categorizer | `memory_hub/categorizer.py` (175 lines) | 144 |
| MCP cwd parity | `memory_hub/mcp_server.py` | — |
| Docs: pipeline is automatic | Docs updated for all 6 hosts | — |
| Test isolation / worker health leak | `tests/conftest.py` | — |
| Priority order recorded | `docs/issue-priority-order.md` | — |
