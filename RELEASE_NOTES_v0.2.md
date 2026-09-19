# AI Memory Hub v0.2

Local-first shared memory for AI tools. Store preferences, decisions and project
notes as readable Markdown, then retrieve them through one MCP server. All data
stays on your machine unless you explicitly enable publication.

---

## Pipeline — Automatic Session Continuity

The auto-context pipeline captures AI tool activity locally, turns it into
compact session summaries, and injects bounded context when you resume work in
any supported tool. Every stage is opt-in and local.

| Feature | What it does |
| --- | --- |
| **Detached worker** | Hook receiver spawns a one-shot `worker --session <id>` child on session-end/stop events; the child outlives the host's hook timeout |
| **Project resolver** | Turns a hook's `cwd` into one stable project slug via vault override map → `.ai-memory-project` pin → nearest `.git` (worktrees collapse) → package marker → leaf name |
| **Capture evidence** | Preserves user prompts, assistant final messages, SessionStart source, StopFailure error type, compaction triggers, plus `host_meta` (transcript_path, model, permission_mode, client_type) |
| **Event normalization** | Gemini CLI and Hermes Agent spellings normalize onto canonical event names (e.g. `beforeagent` → `user-prompt-submit`) |
| **Context injection** | Bounded `additionalContext` packets at SessionStart and per-turn for all six hosts; start packets include latest checkpoint, project facts, and global preferences |
| **Model-free categorizer** | Rule-based extraction of preferences, decisions, git actions and project facts from captured evidence; candidates carry `evidence_ids` |
| **MCP cwd parity** | `memory_context` accepts `cwd` and returns the same packet the hooks inject |
| **Context ledger** | Per-session record under `<vault>/.ai-memory-hub/context-ledger/` prevents injecting the same memory twice in one host session |
| **Config-file settings** | `<vault>/.ai-memory-hub/config.json` is the default source for every setting; dashboard Settings pane renders from `SETTINGS_SCHEMA` |

### Pipeline data flow

```
AI tool lifecycle hook
        │
        ▼
Local observation buffer (SQLite, outside vault)
        │
        ▼
Detached one-shot worker (session-end / stop / compact)
        │
        ├──▶ Project resolver → checkpoint + typed categorizer
        │
        ├──▶ SessionStart / per-turn context packet → additionalContext
        │
        └──▶ Optional: local chat model or evidence-only fallback
```

---

## Security

Defense-in-depth protections for memory writes, the dashboard, and local
process boundaries.

| Feature | What it does |
| --- | --- |
| **Worker env allowlist** | Detached consolidation children receive only `AI_MEMORY_VAULT`, `MEMORY_WRITER`, `MEMORY_WRITE_MODE`, `PATH`, `HOME`, `USERPROFILE` — never the full parent environment |
| **Capture payload sanitization** | `_sanitize_payload()` redacts sensitive fields (API keys, tokens, credentials) before any SQLite write, including transcript append |
| **Dashboard origin protection** | Per-launch random token, `Host`/`Origin` header checks, and `X-Launch-Token` echo defeat DNS rebinding and cross-origin POSTs |
| **Reserved file rejection** | `propose()` rejects any `target_path` whose basename is `memory.md` or `ai_instructions.md` |
| **Payment-card detection** | Candidate regex only allows separators every 4 digits plus a Luhn checksum; internal IDs and arbitrary digit runs pass through |
| **Stale lock recovery** | `file_lock()` reads back the PID and checks liveness; a lock left by a dead process is stolen instead of timing out |
| **Secret pattern checks** | Text validation rejects empty/oversized content and recognizable secrets (defense in depth, not a guarantee) |
| **Sensitive path exclusion** | Built-in `.env`, SSH/AWS credentials, `.pem`, `.key` paths excluded from capture by default |

---

## Performance

Caching, dedup, and efficient queries that keep the pipeline fast and avoid
unnecessary work.

| Feature | What it does |
| --- | --- |
| **Transcript re-render skip** | Per-group content-hash watermark (SHA-256 of event IDs + target); render is skipped when nothing changed |
| **Context packet index caching** | Index rows cached by vault mtime; cache invalidates on vault change |
| **Pre-computed token sets** | Token sets per row computed once to avoid O(N) regex passes per prompt |
| **Single aggregate backlog query** | Worker claims backlog in one query instead of N+1 |
| **Shared helpers** | `one_line`, `is_truthy`, `parse_iso_datetime` extracted to `utils.py` — single source, no duplicated definitions |
| **Stopword filtering** | Expanded `_STOPWORDS` plus `_MIN_CONTENT_TOKEN_LEN` filter and score floor (0.3) so full-trace prompts no longer match unrelated memories |
| **Incremental packet sizing** | `_fit()` tracks byte length incrementally instead of O(n²) re-serialization |
| **Atomic batch claiming** | `claim_for_session` uses single `UPDATE...RETURNING` subquery — no race window |

---

## Quality

Test coverage, operational visibility, and data integrity improvements.

| Feature | What it does |
| --- | --- |
| **395+ tests** | Cover memory, capture, worker, handoff, hooks, sessions, dashboard, patterns, security, embeddings, GitHub export, benchmarks, and pipeline end-to-end |
| **Test isolation** | `tests/conftest.py` scrubs `MEMORY_*`/`AI_MEMORY_*` env vars and redirects `HOME` per test; scratch vaults never litter `~/.ai-memory-hub` |
| **Worker health in vault** | Health file defaults to `<vault>/.ai-memory-hub/worker-health.json` next to `config.json` |
| **Session manifest as single source** | `MemoryManager.session_transcript_target()` is the sole resolver for transcript path/project/summary-links |
| **Vault content preservation** | `update_session_metadata` and `delete_session_block` preserve content above the first `## ` session heading |
| **Index vector safety** | `_embed_record` computes new vectors before deleting old ones; a transient outage leaves existing vectors in place |
| **GitHub export pagination** | `find_issue`/`list_comments` page through every result via `gh api --paginate --slurp` |
| **Worker idle reachable** | Idle now checked before flush, measured from the newest pending row; `MEMORY_WORKER_IDLE_SECONDS` is live at shipped defaults |
| **Degraded run recovery** | A failing run preserves `last_success_at` so "failing for a minute" is distinguishable from "never succeeded" |
| **Codex hook uninstall** | Uninstall now removes a handler alone in its group, matching what `install_codex_hook` creates |
| **Dashboard port/host single source** | `MEMORY_DASHBOARD_PORT`/`MEMORY_DASHBOARD_HOST` used by `app.py`, `dashboard.py`, and all three `start-*.ps1` launchers |
| **Thread-safe caches** | `_covers_cache`, `_entity_registry_cache`, and `_state` all protected by dedicated locks |
| **Specific exception handling** | All broad `except Exception` clauses narrowed to domain-specific exception types |

---

## Memory Workflow

The core shared-memory system that all connected AI clients use.

| Feature | What it does |
| --- | --- |
| **MCP tools** | `memory_search`, `memory_read`, `memory_propose`, `memory_supersede`, `memory_forget`, `memory_context`, `memory_audit`, `memory_reindex` |
| **Session tools** | `session_write` (four sections: Investigated, Learned, Completed, Next Steps), `session_consolidate` |
| **Pattern tools** | `propose_pattern_match` records a project fact and global preference rule atomically |
| **Identity tools** | `project_audit`, `subject_audit`, `project_link`, `entity_alias_link` — preview/apply, no automatic merging |
| **Write modes** | `MEMORY_WRITE_MODE=review` queues proposals for approval; `auto` stores validated proposals directly |
| **Duplicate handling** | Exact duplicates blocked (threshold 0.985); close matches surfaced as `possible_update` for review |
| **Conflict detection** | One-click conflict resolution by superseding competing active entries |
| **MEMORY.md map** | Selective index of active files with `Covers` descriptions; updates automatically |
| **Reindex** | Rebuild the disposable SQLite search index from the Markdown vault |

---

## Multi-Client Support

All six supported AI tools share one vault.

| Feature | What it does |
| --- | --- |
| **Six-host support** | Claude Code, Codex CLI, Gemini CLI, Qwen Code, Kimi Code, Hermes Agent |
| **Auto-detection** | `connect-ai-tools.ps1` auto-detects installed hosts and registers the MCP server |
| **Lifecycle hooks** | `-InstallHooks` installs bounded capture for all six hosts |
| **Startup handoff** | `-InstallHandoff` injects a bounded checkpoint packet at `SessionStart` for all six hosts |
| **Session auto** | `-EnableSessionAuto` turns captured evidence into checkpoint/final proposals |
| **Client prompts** | Behavioral instructions installed per host (Claude, Codex, Gemini, Qwen, Kimi, Hermes, ChatGPT, generic) |

---

## Dashboard

Local browser workspace with no frontend build required.

| Feature | What it does |
| --- | --- |
| **Four color modes** | Standard light/dark plus colorblind light/dark; WCAG-verified contrast |
| **Library** | Search entire indexed library, filter by type, tag, or date; view original Markdown |
| **Review & history** | Approve or reject pending proposals; view recorded statuses |
| **Conflicts** | Explicitly choose a current fact and supersede competing records |
| **Vault health** | Compare files and index without changing records |
| **Edit tags & links** | Add/remove tags and link to stable memory IDs; visible backlinks |
| **Settings pane** | Edit any configuration value grouped by Vault & Identity, Write Mode, Capture, Transcript, Worker, Dashboard, LLM & Embeddings, GitHub Export |
| **Single launcher** | `start-memory-hub.ps1` starts browser dashboard and optional tray icon |
| **Unified tray** | Windows tray launcher with menu; quit via tray or Ctrl+C |
| **Bound to loopback** | Dashboard rejects non-loopback binding by default |

---

## Session Continuity

Optional cross-client session summaries and automatic capture.

| Feature | What it does |
| --- | --- |
| **Session summaries** | Four-section records written automatically at session end |
| **Checkpoint manifests** | Linked session checkpoints with provisional/final entries |
| **Pattern-linked memories** | Record a project fact and global preference rule atomically |
| **Full transcript store** | `MEMORY_TRANSCRIPT_ENABLED=true` retains verbatim provider envelopes in Obsidian (off by default) |
| **GitHub export** | `-EnableGitHubExport` publishes sanitized summaries through a local SQLite outbox (off by default) |
| **Evidence-only fallback** | Consolidation without a local chat model uses deterministic evidence-only fallback |
| **Local embeddings** | Optional semantic search via configurable OpenAI-compatible endpoint (e.g. `nomic-embed-text`) |
| **Vault history** | Opt-in local Git history for undo support |
| **Bulk import** | `scripts/import_sessions.py` imports session summaries from JSON with dry-run preview |

---

## Setup and Connection

PowerShell helpers for Windows; manual configuration for other platforms.

| Feature | What it does |
| --- | --- |
| **setup.ps1** | Creates environment and initializes missing vault files |
| **connect-ai-tools.ps1** | Registers MCP, installs hooks, enables worker/handoff/export |
| **start-memory-hub.ps1** | Launches dashboard and tray together |
| **One-shot worker** | `worker --vault <path> --once` runs a single pass without startup changes |
| **GitHub Actions CI** | Ubuntu + Windows, Python 3.10-3.12, pytest on push/PR |

---

## Recommended first-run mode

Use `MEMORY_WRITE_MODE=review` initially, inspect what each AI tries to retain,
then switch to `auto` once the retention behavior matches your preferences.

> [!WARNING]
> The connection script defaults to review, but a directly started MCP server
> defaults to auto if its mode is missing or invalid. Always configure
> `MEMORY_WRITE_MODE=review` when you want approval before proposals are stored.

---

## What the project does not promise

- It does not guarantee that every provider exposes every event.
- It does not make local storage encrypted.
- It does not silently merge similar people, projects or memories.
- It does not claim live token savings from the replay benchmark.

---

## License

[Apache License 2.0](LICENSE)
