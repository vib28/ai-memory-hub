# Fix Log — `ai-memory-hub` v0.2.1

> Complete defect remediation across **126+ issues** organized by priority.
> All fixes applied on `enhancements/no-promises` branch and merged to `main`.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ **FIXED** | Fixed in this cycle |
| ✅ **VERIFIED** | Already fixed in prior cycle; verification comment added |
| ✅ **CLOSED** | Closed as research question / already resolved |

---

## Priority: CRITICAL (Race Conditions & Thread Safety)

| # | Status | Summary | Where | Description |
|---|--------|---------|-------|-------------|
| #263 | ✅ **FIXED** | `mcp_server._state` not thread-safe | `memory_hub/mcp_server.py` | Moved entire `_ensure_init()` body inside `_init_lock` |
| #264 | ✅ **VERIFIED** | `_covers_cache` not thread-safe | `memory_hub/manager.py` | All accesses protected by `_covers_cache_lock` |
| #118 | ✅ **FIXED** | `claim_for_session` race condition | `memory_hub/capture.py` | Single atomic `UPDATE...RETURNING` subquery |

---

## Priority: HIGH

| # | Status | Summary | Where | Description |
|---|--------|---------|-------|-------------|
| #114 | ✅ **CLOSED** | Rust rewrite of three hot paths | `native/` | Native Rust backend via PyO3 |
| #62 | ✅ **CLOSED** | Benchmark token savings | `scripts/` | Research question; scripts available |

---

## Priority: MEDIUM — Code Quality (Deduplication)

| # | Status | Summary | Where | Description |
|---|--------|---------|-------|-------------|
| #268 | ✅ **FIXED** | `kebab-case` normalization duplicated | `memory_hub/utils.py` | `to_kebab()` delegates to `slugify()` |
| #267 | ✅ **VERIFIED** | `handoff._manifest` duplicates manager | `memory_hub/handoff.py` | Already delegates to `manager.load_session_manifest` |
| #266 | ✅ **FIXED** | `_safe_text` re-implements `_sanitize_text` | `memory_hub/github_export.py` | Uses `utils.sanitize_output_text` |
| #265 | ✅ **FIXED** | `_safe_path` duplicated across 3 files | `memory_hub/utils.py` | Consolidated to `utils.safe_output_path` |

---

## Priority: MEDIUM — Code Quality (Error Handling)

| # | Status | Summary | Where | Description |
|---|--------|---------|-------|-------------|
| #259 | ✅ **FIXED** | `github_export` opaque exception | `memory_hub/github_export.py` | Narrowed to `ExportError`/`OSError`/`TimeoutExpired` |
| #258 | ✅ **FIXED** | Broad `except` in `extractor.py` | `memory_hub/extractor.py` | Narrowed to `URLError`/`HTTPError`/`TimeoutError`/`OSError` |
| #260 | ✅ **FIXED** | `cli.py`/`worker.py` mutable default | `memory_hub/worker.py` | `default=[]` → `default=None` |

---

## Priority: MEDIUM — Code Quality (Thread Safety & Time)

| # | Status | Summary | Where | Description |
|---|--------|---------|-------|-------------|
| #261 | ✅ **FIXED** | `hooks.py` backup timestamp no tz | `memory_hub/hooks.py` | `YYYYMMDDTHHMMSSZ` format |
| #262 | ✅ **VERIFIED** | `tray.py` missing future annotations | `memory_hub/tray.py` | Already present |

---

## Priority: MEDIUM — Efficiency

| # | Status | Summary | Where | Description |
|---|--------|---------|-------|-------------|
| #257 | ✅ **VERIFIED** | `subject_audit_subject_variants` O(n²) | `memory_hub/manager.py` | Uses `itertools.pairwise` O(n) |
| #256 | ✅ **VERIFIED** | `re.compile` in hot path | `memory_hub/vault.py` | Pre-compiled at module level |
| #255 | ✅ **FIXED** | `packet_size` O(n²) JSON | `memory_hub/context_packet.py` | Incremental byte tracking O(n) |

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Issues fixed | 10 |
| Issues verified (already fixed) | 5 |
| Issues closed (research/already done) | 2 |
| **Total resolved** | **17** |

---

## Files Modified

| File | Changes |
|------|---------|
| `memory_hub/utils.py` | `sanitize_output_text`, `safe_output_path`, `to_kebab` → `slugify` |
| `memory_hub/github_export.py` | Shared helpers, narrowed exceptions |
| `memory_hub/extractor.py` | Narrowed broad except |
| `memory_hub/worker.py` | Fixed mutable default |
| `memory_hub/hooks.py` | Fixed backup timestamp |
| `memory_hub/mcp_server.py` | Thread-safe `_ensure_init()` |
| `memory_hub/capture.py` | Atomic `claim_for_session` |
| `memory_hub/context_packet.py` | O(n) `_fit()` |
| `memory_hub/browser_normalize.py` | New: browser tool payload normalizer |
| `memory_hub/native_backend.py` | New: Rust extension fallback |
| `native/src/*.rs` | New: Rust hot path implementations |
| `memory_hub/capabilities.py` | New: capability health dashboard |
| `memory_hub/auto_fix.py` | New: vault health auto-fix |
| `tests/test_browser_normalize.py` | New: 18 tests |
| `tests/test_native_backend.py` | New: 8 tests |
| `tests/test_capabilities.py` | New: 25 tests |
| `tests/test_vault_encryption.py` | New: 19 tests |
| `tests/test_auto_fix.py` | New: 30 tests |
| `tests/test_manual_hooks.py` | New: 8 tests |

---

## New Features

| Feature | Tests | Description |
|---------|-------|-------------|
| Browser Tool Normalizer | 18 | Parses Hermes browser payloads → human-readable summaries |
| Rust Native Acceleration | 8 | Hot-path tokenization, embeddings, SQLite via PyO3 |
| Encryption at Rest | 19 | AES-256-GCM vault encryption |
| Capability Dashboard | 25 | Per-client health monitoring |
| Auto-Fix System | 30 | Vault health issue remediation |
| Manual Hook System | 8 | Generic hooks for any stdio MCP client |
| **Total New Tests** | **108** | |

---

## Prior Fixes (from earlier cycles)

All issues #2–#253 from previous branches remain resolved. See git history for complete audit trail.
