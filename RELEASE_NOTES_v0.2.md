# AI Memory Hub v0.2

## New
- Local browser dashboard bound to 127.0.0.1 with four color modes
- Windows system-tray launcher
- Pending-memory review queue
- `MEMORY_WRITE_MODE=auto|review`
- Approve/reject proposed memories
- Edit stored memories while preserving stable IDs
- One-click forget
- Potential conflict detection by kind + subject
- One-click conflict resolution by superseding competing active entries
- Audit now reports pending items and potential conflicts
- **Six-host support**: Claude Code, Codex CLI, Gemini CLI, Qwen Code, Kimi Code, and Hermes Agent
- `connect-ai-tools.ps1` auto-detects and registers the MCP server for all installed hosts
- Lifecycle capture hooks (`-InstallHooks`) buffer bounded provider events locally for all six hosts
- Session auto worker (`-EnableSessionAuto`) turns captured evidence into checkpoint/final proposals
- Startup handoff (`-InstallHandoff`) injects a bounded local checkpoint at each supported client's SessionStart
- Session summaries (`session_write`) — four-section records (Investigated, Learned, Completed, Next Steps) written automatically at session end
- Pattern-linked memories (`propose_pattern_match`) record a project fact and global preference rule atomically when a recurring situation matches `/patterns.md`
- GitHub export (`-EnableGitHubExport`) publishes sanitized summaries through a local outbox
- Full local transcript store (`MEMORY_TRANSCRIPT_ENABLED=true`) retains verbatim provider envelopes in Obsidian
- Tags and organization editing through lookup, with visible backlinks
- Project-scoped context retrieval
- Optional semantic search via configurable embeddings endpoint
- Backup patterns via Git, Obsidian Sync, OneDrive, Syncthing, or Windows File History

## Validation
- 34 unit and regression tests covering memory, capture, worker, handoff, hooks, sessions, dashboard, patterns, security, embeddings, GitHub export, benchmarks, and pipeline end-to-end
- Python source tree compiled successfully

## Recommended first-run mode
Use `MEMORY_WRITE_MODE=review` initially, inspect what each AI tries to retain, then switch to `auto` once the retention behavior matches your preferences.
