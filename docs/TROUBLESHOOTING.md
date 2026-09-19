# Troubleshooting

> **Start here when something looks wrong.** Find the symptom that matches what
> you're seeing and jump to the fix.

[Installation](INSTALLATION.md) · [Configuration](CONFIGURATION.md) · [Client connections](CLIENTS.md) · [Usage](USAGE.md) · [Dashboard](DASHBOARD.md)

---

## Quick-fix table

| I see… | Go to… |
| --- | --- |
| `uv` not found, Python missing, or setup fails | [Installation fails](#installation-fails) |
| Environment files locked, access denied | [Environment files are locked](#environment-files-are-locked) |
| Client can't see memory tools, MCP missing | [MCP tools are missing](#mcp-tools-are-missing) |
| Memory was proposed but isn't in the vault | [A memory doesn't appear in the vault](#a-memory-doesnt-appear-in-the-vault) |
| Dashboard won't open or port error | [Dashboard won't open](#dashboard-wont-open) |
| "file is not a database" or corrupt index | [Database won't open](#database-wont-open) |
| Hooks installed but no sessions saved | [Hooks are installed but no session is saved](#hooks-are-installed-but-no-session-is-saved) |
| Client hook not firing (unsupported client) | [Manual hook is not firing](#manual-hook-is-not-firing) |
| Transcript is missing or incomplete | [Transcript is missing or incomplete](#transcript-is-missing-or-incomplete) |
| Startup handoff is empty or wrong project | [Startup handoff is empty or ambiguous](#startup-handoff-is-empty-or-ambiguous) |
| GitHub export is queued or failing | [GitHub export is queued or unhealthy](#github-export-is-queued-or-unhealthy) |
| Tests can't create temp directory | [Tests can't create a temporary-directory](#tests-cant-create-a-temporary-directory) |
| Leftover worker-health files in home | [Leftover worker-health files](#leftover-worker-health-files-in-your-home-directory) |

---

## Installation fails

**Symptom:** `setup.ps1` reports `uv not found`, Python is missing, or the script
exits early.

**What to check:**

1. Open a **fresh terminal** after installing prerequisites (the PATH doesn't
   refresh in already-open windows).
2. Confirm both are on PATH:

```powershell
uv --version
python --version   # or: py --version
```

3. If `uv` is missing, install it from
   [docs.astral.sh](https://docs.astral.sh/uv/getting-started/installation/)
   and restart the terminal.
4. If PowerShell blocks the script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

> **Don't** disable execution policy machine-wide. If your organization
> controls policy, ask IT for an exception.

---

## Environment files are locked

**Symptom:** "Access denied", "file in use", or update fails with a lock error.

**Cause:** A running process holds the `.venv` or vault files open — an MCP
server, the dashboard, an editor, or the tray.

**Fix:**

1. Close the terminal running the MCP server (Ctrl+C).
2. Close the dashboard tray icon and its terminal window.
3. If you're unsure, sign out of Windows and back in, then retry the update.

> **Don't** delete `.venv` or the vault to clear a lock. That loses your
> environment and possibly your memories.

---

## MCP tools are missing

**Symptom:** Your AI client (Claude, Codex, Gemini, etc.) can't see the memory
tools, or they appear but don't respond.

**What to check, in order:**

| Check | How |
| --- | --- |
| Connection summary | Re-read the `connect-ai-tools.ps1` output — were all clients skipped? |
| Registered Python path | Does the MCP config point to this repo's `.venv\Scripts\python.exe`? |
| Vault path | Does `AI_MEMORY_VAULT` match the vault you're inspecting? |
| Write mode | `memory_policy` should report the expected mode |
| Workspace trust | The host may have blocked the server — check the client's trust settings |

**Fix:**

1. Start a **fresh client session** after any configuration change. MCP servers
   read their environment at launch, not live.
2. If a client reports "already registered", the old registration may keep stale
   environment values. Remove and re-add it.
3. Verify with the client: ask it to call `memory_policy` and confirm the vault
   path matches.

> **Note:** A successful `connect-ai-tools.ps1` run doesn't guarantee the client
   picked up the new registration. Always start a new session.

---

## A memory doesn't appear in the vault

**Symptom:** You asked the client to remember something, but it's not in the
vault or the review queue.

**Look at the tool result first:**

| Result | Meaning | What to do |
| --- | --- | --- |
| `queued` | Awaiting review | Check the dashboard **Review** tab |
| `possible_update` | Similar memory exists; no auto-write | Review the proposed update |
| `duplicate` | Exact or same-project match found | Read the existing record; distinct projects are scoped separately |
| `rejected` | Failed validation | Read the rejection reason (length, probable-secret, etc.) |
| `stored_without_project_link` | Saved but cross-link missing | Check project configuration |
| Nothing was proposed | Client didn't call propose | Review client instructions and whether the fact qualifies as durable |

**Also check:**

- `memory_policy` — a successful transport response isn't proof of storage.
- Write mode — `review` means it's in the queue, not the vault.
- The correct vault — did the client write to a different `AI_MEMORY_VAULT`?

---

## Dashboard won't open

**Symptom:** Browser shows "connection refused", "port in use", or the launcher
errors out.

**Launch in the foreground to see the actual error:**

```powershell
$memoryVault = Join-Path $env:USERPROFILE "Documents\Obsidian\AI-Memory"
.\start-memory-hub.ps1 -VaultPath $memoryVault
```

**Common fixes:**

| Cause | Fix |
| --- | --- |
| Port 8765 already in use | Change the port (see below) or close the other process |
| Wrong vault path | Verify `-VaultPath` points to your actual vault |
| Host not loopback | `MEMORY_DASHBOARD_HOST` only accepts `127.0.0.1` or `localhost` |

For a one-off different port:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.dashboard --vault $memoryVault --port 8766
```

To change the port permanently, set `MEMORY_DASHBOARD_PORT` consistently across
`app.py`, `dashboard.py`, and every `start-*.ps1` launcher. See
[Configuration](CONFIGURATION.md).

> **Don't** expose the dashboard publicly. Changing the port is not permission
> to bind to `0.0.0.0`.

---

## Database won't open

**Symptom:** "file is not a database" or SQLite errors mentioning corruption.

**This happens when a text file was written over a SQLite database** — for
example, a failed reindex or an editor that replaced the file.

**Recovery steps:**

1. **Stop** all processes using the database (MCP server, worker, dashboard).
2. **Back up** the database and any `.wal` / `.shm` files as a set.
3. Determine whether you have pending review proposals or unsummarized capture
   rows that need recovery.
4. Only after accepting the risk, move the damaged search database aside and
   rebuild from Markdown:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault $memoryVault reindex
```

> **Warning:** Deleting `.memory_index.sqlite3` can lose **pending proposals**.
> Deleting the capture database loses **unsummarized observations**. `reindex`
> cannot restore either from Markdown — it only rebuilds the search index from
> accepted records.

---

## Hooks are installed but no session is saved

**Symptom:** The client is running, capture hooks are installed, but nothing
appears in the vault or the sessions folder.

**Capture alone doesn't create sessions.** The worker must also be running, and
in `review` mode the proposal waits in the dashboard queue.

**Check in this order:**

1. **Is the capture database receiving rows?**
   Check the `MEMORY_CAPTURE_DB` path the client writes to.
2. **Is the worker running?**
   Inspect worker health and look for pending rows. A lease in progress is not
   an accepted session yet.
3. **Run one pass manually:**

```powershell
.\.venv\Scripts\python.exe -m memory_hub.worker --vault $memoryVault --once
```

4. **Check write mode:** `review` queues a proposal; `auto` can accept it.
5. **Read the result:** Check the `/sessions/...` Markdown and its manifest.

> **Don't** repeatedly reinstall hooks into personal settings. CLI help output
> or valid JSON alone doesn't prove event delivery. See
> [Client connections](CLIENTS.md) for the tested version matrix.

---

## Manual hook is not firing

**Symptom:** You used `-InstallManualHook <name>` but the hook never fires when
the client runs a tool, or it fires but nothing is captured.

**Check in this order:**

1. **Does the client actually run the hook?**
   Open the settings file specified by `-ManualHookSettings` and confirm the
   entry is there with the correct command path. Not all clients pass stdin
   JSON correctly — test with a simple wrapper script first:

   ```powershell
   @'
   $input | Out-File -Encoding UTF8 "$env:TEMP\hook-test.log"
   '@ | Set-Content "$env:TEMP\hook-wrapper.ps1"
   ```

   Point the hook at this wrapper, trigger a tool call, and check the log.

2. **Is `ai-memory-hook` on the path the client sees?**
   The script uses the venv's copy directly, but some clients spawn hooks in a
   stripped environment. If the client can't find the binary, use the full
   path to `ai-memory-hook.exe` in the venv's `Scripts` directory.

3. **Is the worker running?**
   The hook only writes to the observation buffer — the worker must be running
   to process it. Run with `-EnableSessionAuto` or start the worker manually:

   ```powershell
   .\start-worker.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory"
   ```

4. **Wrong event name?**
   The default is `PostToolUse`. If your client uses a different event name
   (e.g., `afterToolUse`, `tool_call_complete`), pass it with `-ManualHookEvent`.
   Check your client's documentation for the exact event names it supports.

5. **Settings file format mismatch?**
   The `-InstallManualHook` flag uses the `claude` format (nested matcher groups).
   If your client expects a flat array instead, you may need to edit the
   settings file manually. See [templates/manual-hook-config.md](../templates/manual-hook-config.md)
   for the generic JSON shape.

6. **Backup files accumulating?**
   The script creates `.bak-*` files on every write. These are safe to delete
   after confirming the current settings are correct.

---

## Transcript is missing or incomplete

**Symptom:** Full-session transcripts aren't being saved, or they're truncated.

**Transcripts are opt-in and default-off.** Confirm all of the following were
set **before** the hook receiver and worker started:

- `MEMORY_TRANSCRIPT_ENABLED=true`
- `AI_MEMORY_VAULT`
- `MEMORY_TRANSCRIPT_DB` (if overridden)

**Fix:**

1. Restart the hook receiver and worker after changing any transcript setting.
2. Check the worker health record for `transcript_rendered`, `transcript_deleted`,
   and any transcript error.
3. Verify the configured path is writable and the SQLite file isn't locked.

> **Privacy note:** Raw transcript values are **not** subject to bounded
> observation redaction. If you enabled this accidentally, stop the hook
> process, review local backups, and use the session forget path for any
> records you didn't intend to keep.

---

## Startup handoff is empty or ambiguous

**Symptom:** The client starts with no prior context, or the handoff shows the
wrong project.

**The handoff reader is local and offline** — it uses only
`/sessions/session-manifest.json` and referenced Markdown. It does not call MCP,
embeddings, a chat model, or GitHub.

| Symptom | Likely cause |
| --- | --- |
| Empty result | No accepted checkpoint, missing/invalid manifest, or wrong project/worktree |
| Ambiguous result | Intentional — active work groups are listed separately, not merged |

**Fix:**

1. Confirm the handoff permission is installed:

```powershell
.\connect-ai-tools.ps1 -VaultPath $memoryVault -InstallHandoff
```

2. Verify a checkpoint was actually accepted (not just queued in review).
3. Check that the manifest identifies the correct project slug.
4. Confirm you're on the right worktree — handoff is scoped per project.

> **Note:** Only Claude Code, Codex CLI, Gemini CLI, Qwen Code, Kimi Code, and
> Hermes Agent currently have process-level startup fixtures. A successful hook
> command doesn't certify that an installed client version actually delivered
> the event.

---

## GitHub export is queued or unhealthy

**Symptom:** Export is enabled but nothing appears on GitHub, or the health
check shows failures.

**Export is opt-in and independent from local handoff.** Check each layer:

| Layer | What to verify |
| --- | --- |
 | Destination | `owner/name` approved, visibility set (`public`, `private`, `internal`) |
| Credentials | `gh auth status` — is the token valid? |
| Health JSON | Check the exporter health file |
| Outbox | Inspect the SQLite outbox for queued rows |

**Failure behavior:**

- Offline or timeout failures remain **retryable** — don't delete the outbox.
- Pending review proposals are **never** exported.
- Disabling export stops the startup entry but **retains** queued work.

> **Don't** delete the outbox while diagnosing. It contains stable markers that
> prevent duplicate issues and comments on retry.

---

## Tests can't create a temporary directory

**Symptom:** pytest fails with "inaccessible temporary root" or similar.

Use a fresh, task-specific base path:

```powershell
$memoryTestBase = Join-Path $env:TEMP ("ai-memory-tests-" + [guid]::NewGuid().ToString("N"))
.\.venv\Scripts\python.exe -m pytest -q --basetemp $memoryTestBase
```

> **Never** point `--basetemp` at a vault, repository, or any directory
> containing data you need. pytest manages (and may delete) that directory.

---

## Leftover worker-health files in your home directory

**Symptom:** You see `worker-health-<hash>.json` files under `~/.ai-memory-hub/`
and don't know if they matter.

These are leftovers from older builds. Health now lives at:
`<vault>/.ai-memory-hub/worker-health.json`.

**Fix:** Files matching `worker-health-*.json` in the home directory are safe to
delete. The worker still reads the old path as a one-release fallback, but it's
not required.

---

## Still stuck?

1. **Read the error message carefully** — the system tries to explain what went
   wrong and where.
2. **Check worker health** — the dashboard's `/api/worker-health` endpoint and
   the per-vault `worker-health.json` record show what the worker sees.
3. **Back up before changing anything** — copy accepted Markdown plus pending
   review/capture databases.
4. **Open an issue** with:
   - Exact reproduction steps
   - Expected behavior
   - Actual results (copy the error text)
   - Your environment (OS, branch, client versions)

Use **synthetic examples**, not credentials or real vault contents. See
[Contributing](../CONTRIBUTING.md#issue-workflow).

If the tray can't run on your desktop, use `start-memory-hub.ps1 -NoTray`.
If the palette is hard to read, try **Dark mode** and **Colorblind** toggles in
the dashboard header. See the [dashboard guide](DASHBOARD.md).
