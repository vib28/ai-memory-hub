# No Promises Fix Plan

## 1. No Encryption → Encryption at Rest
- Add `VAULT_ENCRYPTION_KEY` environment variable (32-byte hex string, user-managed)
- Encrypt all `.md` files at rest using AES-256-GCM with the user's key
- Decrypt transparently on read
- New vault files default to encrypted; existing vaults can be migrated via CLI
- Key derivation: HKDF-SHA256 from user passphrase if preferred
- Dashboard shows encryption status

## 2. No Silent Merging → Visible Deduplication UI
- Already correct: similar items stay in review queue
- Add a "Find Similar" button on pending proposals that shows exact/semantic matches
- Add a one-click "Merge into existing" action in the dashboard
- Document the workflow clearly in USAGE.md

## 3. Startup Hooks → Extensible Hook System
- Already implemented for 6 clients (Claude, Codex, Gemini, Qwen, Kimi, Hermes)
- Add a documented "Manual Hook" pattern for any stdio MCP client
- Add a generic `--InstallManualHook <client-name>` flag
- Add troubleshooting for common client-specific hook failures

## 4. No Guaranteed Recovery → Capability Health Dashboard
- Add a per-client health indicator in the dashboard showing:
  - Which events are supported (green/yellow/red)
  - Capture buffer depth
  - Last successful capture timestamp
- Add a CLI `doctor --clients` command that tests each installed client's hook
- Document the capability matrix clearly
