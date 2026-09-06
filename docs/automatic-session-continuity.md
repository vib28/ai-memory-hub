# Automatic session continuity

Status: **designed and tracked, not implemented**. Reviewed 2026-09-07 against
`enhancements/roadmap` at `0bac560`. Parent: [#61](https://github.com/vib28/ai-memory-hub/issues/61).

## Where the problem exists

The capture-to-handoff path spans client installation, observation buffering,
consolidation, session persistence, retrieval and dashboard presentation. Current
components do not yet form an unattended session-saving service.

Review coverage: capture.py, hooks.py, session_capture.py, consolidator.py,
manager.py session/context paths, vault.py routing/parsing/deletion, models.py,
index.py retrieval and pending records, mcp_server.py, CLI/setup/connection entrypoints,
tray responsibilities, security/history boundaries, client prompts, relevant tests,
CI configuration, README, architecture and roadmap/usage/installation documentation.
This is a cross-component architecture review, not a claim that every code path was
exercised or that every installed client was certified.

## Why it matters

The user's **first priority** is automatic periodic state saving and automatic
cross-client handoff, linked through metadata, forward/backward navigation and tags.
No routine save, summarize, restore or publish commands should be needed.

This should reduce repeated explanations and unnecessary context replay. It does not
guarantee a token-saving percentage, exact conversation replay, or recovery of words
the source client never emitted. Local continuity comes before optional GitHub publishing.

## How the fix works

### Reuse the existing foundation

| Existing component | Reuse | Missing work |
|---|---|---|
| Generic stdin receiver / SQLite buffer | Fast, local evidence capture | Native adapters, privacy filtering, stable event identity |
| Local SLM / deterministic fallback | Summarize without remaining cloud quota | Supervised scheduling, bounded batches and useful fallback state |
| Four-section session blocks | Human-readable checkpoint and final template | Group/batch metadata, navigation, rollup and parser roundtrip |
| Public MCP write policy / review queue | Govern accepted durable memory | Idempotent batch submission and explicit session-auto scope |
| Git history | Reversible accepted changes | Recoverable batch/manifest publication and history error tracking |
| FTS / optional vectors | Related-memory retrieval | Deterministic active-session selection and strict context scope |
| Hook installers | Backups and managed installation | Correct schemas, mixed-handler preservation, full lifecycle setup |

The capture database is **durable operational state**, not a disposable search index.
Unsummarized evidence cannot be reconstructed from the Markdown vault. Pending review
payloads also currently live in SQLite and are not recoverable from accepted Markdown
alone. Do not delete either while assuming reindex restores everything.

### Automatic flow

```text
client event -> sanitize and persist local evidence
                         |
              supervised local worker
                         |
          ordered checkpoint + session manifest
                  /                  \
    bounded local handoff packet     accepted session-write policy
               |                           |
 next client's start hook          Markdown / review queue
                                           |
                               permitted GitHub export outbox
```

Heavy summarization and network publication never run inside the synchronous capture
hook. Start hooks read a ready local packet with a short deadline; they must not wait
for a local model or GitHub. If new evidence is still being summarized, show checkpoint
age and a bounded, sanitized pending-evidence delta rather than pretending it is current.

### Lifecycle and client capability

Current connection code installs only PostToolUse, except Gemini's AfterTool. Hermes
and other MCP clients have separate memory access but no lifecycle installation here.
The receiver's event aliases do not establish native event delivery.

The current [Claude hook reference](https://code.claude.com/docs/en/hooks) documents
start, prompt, tool, stop, compaction and end events, plus StopFailure with rate_limit.
Start-hook output can add context. These are possible adapter inputs, not installed
features of this repository. Failure notification is not advance warning of quota
exhaustion; abrupt termination may emit nothing.

The current [Codex hook guide](https://learn.chatgpt.com/docs/hooks) documents
SessionStart context output and lifecycle events. MCP may not be ready at start;
SessionEnd does not support MCP hooks. Background hooks may be cancelled when a
session ends. Therefore use a quick command hook and a separately supervised worker.
Transcript format is not a stable hook interface: any optional tail reader must be
versioned, bounded and allowlisted rather than silently scanning all histories.

Implementation must record tested versions and capabilities for each actual client
surface. Claude/Codex CLI support must not be assumed for desktop, cloud, Gemini,
Qwen, Kimi or Hermes. If a host cannot emit events or accept startup context, an
explicitly configured wrapper or supported log adapter may provide automation;
otherwise report that host as unsupported. Prompt instructions alone are best effort.

Capture user submissions, tool outcomes and completed assistant-turn evidence where
the host exposes them. Keep source-client identity separate from event source
(startup/resume/compact). Stop finishes a turn, not necessarily a session.
Quota errors, normal exit and expired heartbeat all request a flush, but an idle
timeout produces a provisional/incomplete final, not a claim the work was completed.

### Token and time checkpoints

No native every-N-token hook is required: local code can count incoming evidence and
schedule a checkpoint when a threshold is reached.

Maintain separate values for:

- host-reported model usage, including whether it is cumulative, a delta or context size;
- tokens in the sanitized captured evidence, counted by a named tokenizer when possible;
- estimated evidence tokens when a tokenizer/host count is unavailable;
- tokens in the outgoing handoff packet.

Never call an evidence estimate a billed-token count or subtract cached/repeated
context usage without a documented accounting rule. Suggested starting settings for
evaluation: 4,000 estimated evidence tokens, or 60 seconds with new evidence, whichever
comes first. These are tunable design defaults, not measured optimum values.
Additional turn/compaction/failure/end triggers coalesce with scheduled flushes.
Split oversized events safely and preserve evidence offsets without double-counting.

The worker starts automatically after one-time setup, survives client termination,
uses leases to avoid concurrent claims and retries failed operations with bounded
backoff. A missing local SLM uses an honest evidence-only checkpoint; do not infer
decisions or successful tests from a command merely having been issued.
Benchmark fallback usefulness separately from SLM summaries.

### Session identity, metadata and real navigation

Use two identities: a host session belonging to one client and a work group that can
continue across Claude and Codex. Resolve project identity from configured repository
mapping plus canonical workspace/worktree scope, not embeddings, title prefixes,
raw credential-bearing remote URLs or the consolidating client's writer name.

Proposed versioned metadata:

| Field | Meaning |
|---|---|
| schema_version, project_id, workspace_id | Stable scope and migration version |
| session_group_id, host_session_id, source_client | Work group and original provenance |
| checkpoint_id, sequence, entry_type | Unique batch and checkpoint/final role |
| previous_id, next_id, final_id | Machine-readable chain, explicit null at endpoints |
| evidence_start, evidence_end, idempotency_key | Exactly which evidence this batch owns |
| token_count, token_basis, tokenizer | Count and its honest interpretation |
| created_at, checkpoint_at, state, revision | Age, provisional/final state and recovery |
| previous_url, next_url, final_url, tags | Human navigation and export identity |

Keep the existing Investigated / Learned / Completed / Next Steps headings for every
checkpoint and final entry. Put metadata outside the narrative sections so counting,
hashing and reindexing do not mistake it for a new fact. Preserve old session blocks.

A canonical, versioned group manifest lists all checkpoint IDs, file/heading anchors
and final revisions. SQLite can index this manifest but must not be its only surviving
copy after accepted publication. The operational pre-approval manifest stays outside
the vault and is labeled unreviewed.

When B2 is published, set B1.next=B2 and B2.previous=B1 automatically; when a final
rollup is published, link it to all batches and update the final pointer. Use actual
`[[sessions/project/writer#heading]]` links, not a bare title that has no file target.
Shared tags include the group, project, source client and checkpoint/final role.
Tags supplement IDs; they are not identity themselves.

Several Markdown files cannot be assumed to update atomically. Use a durable operation
journal, fixed IDs and recoverable manifest revisions; audit and repair incomplete
navigation after restart. Git commits give undo but do not replace a write transaction.
Never silently overwrite human edits while repairing an owned metadata block.

A host-session final can coexist with an active work group. On continuation, append
a new checkpoint/final revision with provenance rather than erasing the old final.
The final rollup covers every batch and retains unresolved questions and next steps.
If several active tasks share a workspace, automatically present separate compact
candidates without guessing they are the same session.

### Handoff content and trust

The start hook loads, in order: the active work group's latest checkpoint/final state,
explicit goal and constraints, decisions, files/branch/commit references, verified
results, unresolved work and next action. Supplement only with scoped durable memories.
Read the local checkpoint without needing embeddings. Follow links on demand instead
of replaying the whole transcript.

Treat summaries and captured text as evidence, not executable instructions. Separate
user-stated constraints, model claims and verified outcomes; flag stale branch/worktree
information. Revalidate repository state before the next agent acts on a checkpoint.
Do not inject another project's records merely because words match.

### One-time setup, then unattended operation

Setup separately configures capture, session-auto persistence, startup integration,
vault undo and GitHub export destination/visibility. Defaults must be explicit and
consistent: the current connection script selects review, but the MCP module's
unset/invalid environment fallback is auto. Do not describe review as a universal
runtime default before resolving that difference for the new service.

Automatic local checkpointing and handoff must not depend on approving each summary.
Operational unreviewed state may be supplied as clearly labeled evidence; accepted
durable-memory writes still follow their configured policy. Explicit session-auto
enables fully unattended canonical session saving. This does not authorize automatic
merging/deleting preferences or exporting the whole vault.

Set retention, sensitive-file exclusions, payload limits and access permissions before
persisting evidence. Sanitization is defense in depth, not a guarantee that arbitrary
private text is safe to publish. Installation/startup registration must be reversible,
hidden on Windows and preserve unrelated settings. Surface worker health and backlog
automatically in the dashboard.

### GitHub session entries

Proposed layout: one session issue per work group, ordered checkpoint comments, and a
final-summary comment. Every batch/final uses the same four headings; metadata includes
group/batch IDs, previous/next/final URLs, source, evidence range and token basis.
The issue body carries an automatically maintained index. Comments have no native
GitHub labels, so batch tags are stored in body metadata; parent labels group the log.

An explicitly configured export policy publishes only sanitized permitted summaries.
The outbox reconciles a stable marker after an uncertain timeout, retries offline/rate
limit failures and updates only owned blocks. Never close bug issues merely because a
session final exists. GitHub is a publication mirror, not required for local handoff.

The existing seven-section issue/roadmap format remains unchanged. Session artifacts
use the four-section session template; engineering work tracking uses where/why/how,
reproduction, acceptance, implementation and verification.

## Reproduction steps

Disposable checks on the baseline produced:

| Issue | Reproduction | Observed result |
|---|---|---|
| #52 | Native PostToolUse payload with tool_name=Edit | event=observation, tool=unknown, files empty; retry ID changed |
| #53 | Add sibling user-hook, reinstall nested/Codex hook | Sibling missing in both formats |
| #54 | 501 ordered rows, first 500 completed | Consolidation empty although session still pending |
| #54 | Recover a freshly claimed processing row | Reclaimed immediately, no lease/owner check |
| #55 | Same writer/title/sections in alpha then beta | First stored, second duplicate |
| #56 | Stub one 2,000-character foreign-project result, budget=500 | 2,101 characters and foreign path returned |

The context check used a stub to isolate the boundary; it is not a real-client
injection test. Queue recovery proves the missing lease guard, not an observed
simultaneous double-write. Issue bodies give reproduction and acceptance detail.

## Acceptance criteria

- Required gate [#62](https://github.com/vib28/ai-memory-hub/issues/62): run matched
  Claude→Codex and Codex→Claude sessions with context passing ON/OFF using the
  [prescribed seven-section benchmark protocol](session-handoff-benchmark.md).
  Include both tools, local summarization overhead and re-explanation, and report task
  correctness alongside token savings. No measured result is available yet.
- No routine user-triggered save, consolidation, finalization, restore or posting.
- Three or more token/time checkpoints and a final rollup retain valid links, tags
  and metadata across approval, restart and reindex.
- Bidirectional Claude/Codex handoff restores the useful task state without
  depending on paid quota, embeddings or GitHub.
- Long sessions, duplicate delivery, concurrent workers and interruption at each
  write/ack/link/export boundary preserve accepted evidence without duplicate batches.
- Strict context budget, project isolation, pending/stale labels and secret filtering.
- Test actual supported-client event delivery and startup injection, including spaces
  in executable paths and normal shutdown versus forced termination.
- Measure handoff token size against full transcript and current memory_context
  baselines on the same tasks, alongside recall of decisions/next steps, checkpoint
  age, latency and repeated explanation. Do not improve savings by silently losing
  essential information.
- Run native-fixture and end-to-end automated tests in CI; real-client checks must
  name versions, required credentials and skipped cases. Ruff cannot test behavior.

## Implementation details

**Top-priority order**, ahead of #40 and unrelated #41–#51 cleanup:

1. [#52](https://github.com/vib28/ai-memory-hub/issues/52) native adapters and
   [#53](https://github.com/vib28/ai-memory-hub/issues/53) safe hook updates.
2. [#54](https://github.com/vib28/ai-memory-hub/issues/54) queue correctness and
   [#55](https://github.com/vib28/ai-memory-hub/issues/55) session identity.
3. [#57](https://github.com/vib28/ai-memory-hub/issues/57) checkpoint metadata and links.
4. [#58](https://github.com/vib28/ai-memory-hub/issues/58) local automatic worker.
5. [#56](https://github.com/vib28/ai-memory-hub/issues/56) context scope/budget and
   [#59](https://github.com/vib28/ai-memory-hub/issues/59) automatic startup handoff.
   The boundary fix can be prepared earlier.
6. [#60](https://github.com/vib28/ai-memory-hub/issues/60) GitHub publication.
7. Automated cross-client/failure tests and the required paired ON/OFF benchmark #62,
   with measured token/quality closeout in #61.

Keep this dependency line coordinated. #42 retains ownership of readable project
cross-links; #41 remains authoring guidance. #40's section vectors can improve later
retrieval but do not capture missing events or establish session identity. #50/#51
are not prerequisites for using the already-supported multi-line session kind.
Do not duplicate or silently close these existing open items.

## Verification results

Existing tests: 148 passed, two setup errors accessing the existing pytest temporary
root; the two affected pruning tests passed in a fresh temporary folder. Ruff passed.
This is not a single clean 150-test full run and not certification of automation.

No runtime feature, personal hook configuration, startup service or real memory
vault was changed by this review. No automatic GitHub session content was published.
Native host event delivery, live quota interruption and full cross-client restoration
remain acceptance work. Proposed issues stay open until implemented and verified.
