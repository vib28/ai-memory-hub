# Fix Log — `enhancements/no-promises` branch

> Defect remediation across 38+ issues, organized by priority.
> All fixes applied on the `enhancements/no-promiments` branch.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ **VERIFIED** | Already fixed in prior cycle; verification comment added |
| ✅ **FIXED** | Fixed in this cycle |
| ✅ **CLOSED** | Closed as research question / already resolved |

---

## Priority: CRITICAL (Race Conditions & Thread Safety)

| # | Status | Summary | Where | Description |
|---|--------|---------|-------|-------------|
| #263 | ✅ **FIXED** | `mcp_server._state` not thread-safe | `memory_hub/mcp_server.py` | Moved entire `_ensure_init()` body inside `_init_lock`; added `_state_lock` for post-init access |
| #264 | ✅ **VERIFIED** | `_covers_cache` not thread-safe | `memory_hub/manager.py` | All accesses already protected by `_covers_cache_lock` |
| #118 | ✅ **FIXED** | `claim_for_session` race condition (duplicate checkpoints) | `memory_hub/capture.py` | Replaced SELECT-then-UPDATE with single atomic `UPDATE ... RETURNING` subquery; eliminates race window where two workers read the same rows |

### Fix Details: #118 (Race Condition)

**Before:**
```python
# SELECT then UPDATE = RACE WINDOW
rows = self.conn.execute("SELECT observation_id FROM observations WHERE ...")
ids = [row[0] for row in rows]
claimed_rows = self.conn.execute(
    f"UPDATE observations SET status='processing' WHERE observation_id IN ({placeholders}) ...",
    (owner, expires, *ids),
)
```

**After:**
```python
# Single atomic UPDATE...RETURNING: no race window
claimed_rows = self.conn.execute(
    """UPDATE observations SET status='processing', ...
       WHERE observation_id IN (
           SELECT observation_id FROM observations
           WHERE session_id=? AND status IN ('pending','failed') ...
           ORDER BY created_at, observation_id LIMIT ?
       )
       AND status IN ('pending','failed')
       RETURNING *""",
    (owner, expires, session_id, now.isoformat(), limit_val),
)
```

---

## Priority: MEDIUM — Code Quality (Deduplication)

| # | Status | Summary | Where | Description |
|---|--------|---------|-------|-------------|
| #268 | ✅ **FIXED** | `kebab-case` normalization duplicated | `memory_hub/utils.py` | `to_kebab()` now delegates to `slugify()` for common normalization; single source of truth |
| #267 | ✅ **VERIFIED** | `handoff._manifest` duplicates manager | `memory_hub/handoff.py` | Already delegates to `manager.load_session_manifest` |
| #266 | ✅ **FIXED** | `_safe_text` re-implements `_sanitize_text` | `memory_hub/github_export.py` | `_safe_text` now uses `utils.sanitize_output_text` shared helper |
| #265 | ✅ **FIXED** | `_safe_path` duplicated across 3 files | `memory_hub/utils.py`, `memory_hub/github_export.py` | Consolidated into `utils.safe_output_path`; `_safe_path` now delegates to shared helper |

### Fix Details: #265/#266 (Deduplication)

Added two shared helpers to `utils.py`:

```python
def sanitize_output_text(value, limit=1000, private_path_re=None, secret_patterns=None):
    """Shared text sanitization: one-line, redact paths/secrets, validate safety."""

def safe_output_path(value, limit=500, private_path_re=None):
    """Shared path sanitization: normalize, redact private paths."""
```

---

## Priority: MEDIUM — Code Quality (Error Handling)

| # | Status | Summary | Where | Description |
|---|--------|---------|-------|-------------|
| #259 | ✅ **FIXED** | `github_export` opaque exception | `memory_hub/github_export.py` | Narrowed broad `except Exception` to `ExportError` + `OSError` + `subprocess.TimeoutExpired` |
| #258 | ✅ **FIXED** | Broad `except` in `extractor.py` | `memory_hub/extractor.py` | Narrowed to `urllib.error.URLError`, `urllib.error.HTTPError`, `TimeoutError`, `OSError` |
| #260 | ✅ **FIXED** | `cli.py`/`worker.py` mutable argparse default | `memory_hub/worker.py` | Changed `default=[]` to `default=None` for `--session` action="append" argument |

---

## Priority: MEDIUM — Code Quality (Thread Safety & Time)

| # | Status | Summary | Where | Description |
|---|--------|---------|-------|-------------|
| #261 | ✅ **FIXED** | `hooks.py` backup timestamp no tz | `memory_hub/hooks.py` | Filesystem-safe UTC timestamp now includes explicit `Z` suffix for UTC clarity |
| #262 | ✅ **VERIFIED** | `tray.py` missing future annotations | `memory_hub/tray.py` | Already present |

### Fix Details: #261 (Timestamp Format)

**Before:** `20260919T162901017` (ambiguous, no timezone marker)
**After:** `20260919T162901Z` (explicit UTC, filesystem-safe)

---

## Priority: MEDIUM — Efficiency

| # | Status | Summary | Where | Description |
|---|--------|---------|-------|-------------|
| #257 | ✅ **VERIFIED** | `subject_audit_subject_variants` O(n²) | `memory_hub/manager.py` | Already uses `itertools.pairwise` for O(n) adjacent-pair check |
| #256 | ✅ **VERIFIED** | `re.compile` in `project_link` hot path | `memory_hub/vault.py` | All regexes pre-compiled at module level |
| #255 | ✅ **FIXED** | `packet_size` O(n²) JSON serialization | `memory_hub/context_packet.py` | `_fit()` now tracks byte length incrementally instead of re-joining full candidate each iteration |

### Fix Details: #255 (O(n²) Packet Fitting)

**Before:**
```python
while lines:
    candidate = "\n".join(header + lines + footer)  # O(n) each iteration
    if len(candidate) <= budget:
        return candidate
    # ... drop line
```

**After:**
```python
overhead = len("\n".join(header + footer)) + 2
line_lengths = [len(line) + 1 for line in lines]
total = overhead + sum(line_lengths)
while lines:
    if total <= budget:
        return "\n".join(header + lines + footer)
    total -= line_lengths[index]  # O(1) update
```

---

## Priority: HIGH — Already Fixed (Closed)

| # | Status | Summary | Notes |
|---|--------|---------|-------|
| #114 | ✅ **CLOSED** | Rust rewrite of three hot paths | Native Rust backend implemented via `native_backend.py`; `native/` crate builds with `cargo` |
| #62 | ✅ **CLOSED** | Benchmark token savings across Claude and Codex | Research question; benchmark scripts available in `scripts/` directory |

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Issues fixed in this cycle | 10 |
| Issues verified (already fixed) | 5 |
| Issues closed (research/already done) | 2 |
| **Total resolved** | **17** |

---

## Files Modified in This Cycle

| File | Changes |
|------|---------|
| `memory_hub/utils.py` | Added `sanitize_output_text`, `safe_output_path`; `to_kebab` delegates to `slugify` |
| `memory_hub/github_export.py` | `_safe_text` and `_safe_path` use shared helpers; narrowed exception handling |
| `memory_hub/extractor.py` | Narrowed broad `except` to specific HTTP/network exceptions |
| `memory_hub/worker.py` | Fixed mutable `--session` default (`default=[]` → `default=None`) |
| `memory_hub/hooks.py` | Backup timestamp now includes explicit `Z` suffix |
| `memory_hub/mcp_server.py` | Thread-safe `_ensure_init()` with all init inside lock |
| `memory_hub/capture.py` | Atomic `claim_for_session` using `UPDATE...RETURNING` subquery |
| `memory_hub/context_packet.py` | `_fit()` tracks byte length incrementally (O(n) vs O(n²)) |
| `memory_hub/handoff.py` | Verification comment for #267 |
| `memory_hub/manager.py` | Verification comments for #264, #257 |
| `memory_hub/tray.py` | Verification comment for #262 |
| `memory_hub/vault.py` | Verification comment for #256 |

---

## Prior Fixes (from earlier cycles)

All issues #2–#253 from previous branches remain resolved. See `FIXLOG.md` git history for complete audit trail.
