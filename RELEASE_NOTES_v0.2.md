# Release Notes — v0.2.1

> **Date:** 2026-09-19  
> **Branch:** `main`  
> **Tests:** 445+ passing  
> **Issues:** 0 open (all closed)

---

## 🚀 New Features

### Browser Tool Normalizer
- Automatically parses Hermes browser tool payloads into human-readable summaries
- Detects screenshots, clicks, typing, navigation, scrolling, element-find, console checks
- Example: `[{"text": "Successfully captured screenshot (1568x709, jpeg)", "type": "text"}]` → `Screenshot captured (1568x709, jpeg)`

### Rust Native Acceleration
- Hot-path operations (tokenization, embeddings, SQLite) ported to Rust via PyO3
- Graceful fallback to Python if Rust extension unavailable
- Enabled via `MEMORY_NATIVE_BACKEND=true` (default)

### Encryption at Rest
- AES-256-GCM encryption for vault `.md` files
- Enabled via `VAULT_ENCRYPTION_KEY` environment variable
- CLI commands: `vault-key`, `vault-encrypt`, `vault-decrypt`, `vault-status`

### Capability Health Dashboard
- Per-client hook status, buffer depth, last capture timestamp
- Endpoint: `GET /api/capabilities`
- CLI: `ai-memory doctor --clients`

### Auto-Fix System
- Detects and repairs: malformed lines, orphan session blocks, duplicate IDs, stale index entries
- Dashboard: `Vault health` view with one-click `Auto-Fix` buttons
- CLI: `fix_issue()` API for programmatic remediation

### Manual Hook System
- Generic hooks for any stdio MCP client via `-InstallManualHook <name>`
- Template: `templates/manual-hook-config.md`

---

## 🐛 Bug Fixes

| # | Summary | Impact |
|---|---------|--------|
| #263 | `mcp_server._state` not thread-safe | Race condition eliminated |
| #118 | `claim_for_session` atomic UPDATE...RETURNING | No more duplicate checkpoints |
| #261 | Backup timestamp includes explicit `Z` suffix | Filesystem-safe, unambiguous |
| #260 | `worker.py` mutable argparse default | No more shared state bugs |
| #259/#258 | Narrowed broad exceptions | Better error diagnostics |
| #255 | `_fit()` O(n) packet sizing | Faster context injection |

---

## 🔧 Refactoring

| # | Summary | Impact |
|---|---------|--------|
| #268 | `to_kebab()` delegates to `slugify()` | Single source of truth |
| #266/#265 | Shared `sanitize_output_text` / `safe_output_path` | No more duplication |
| #264 | `_covers_cache` thread-safe with dedicated lock | Concurrent access safe |
| #262 | `tray.py` has `from __future__ import annotations` | Consistency |
| #257 | `subject_audit_subject_v01_variants` uses `itertools.pairwise` | O(n) vs O(n²) |
| #256 | All regexes pre-compiled at module level | No hot-path re.compile |

---

## 📚 Documentation

- `README.md` — Complete rewrite with badges, tables, architecture diagram
- `FIXLOG.md` — Comprehensive fix history with 126+ issues tracked
- `docs/cold-start-summary.md` — Full conversation summary for context restoration
- `docs/restart-guide.md` — Quick start guide with architecture diagram
- `docs/browser-normalize-closeout.md` — Browser normalizer design doc

---

## 📊 Statistics

| Metric | Value |
|--------|-------|
| Tests | 445+ passing |
| GitHub Issues | 0 open |
| Clients Supported | 6 (5 with hooks installed) |
| Rust Extensions | Built and loaded |
| Documentation | Complete |
