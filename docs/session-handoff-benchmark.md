# Two-tool handoff benchmark protocol

Required acceptance gate for #61; tracked in #62. This is a test design, not a measured result.

## Where the problem exists

The evaluation section of docs/local-memory-plan.md and the automatic-continuity phase #61. Existing scripts/benchmark_context.py compares context packet sizes; it does not perform matched work across two different AI tools or measure re-explanation after switching.

## Why it matters

The user requires evidence of how many tokens automatic context passing saves for a similar session across two tools, compared with leaving context passing disabled. A smaller prompt is not a win if the second tool loses decisions, repeats completed work or fails the task.

## How the fix works

Build an automated, paired benchmark for Claude→Codex and Codex→Claude. Use the same source transcript/evidence, repository snapshot, task, handoff point, destination model/settings and final acceptance checks in each pair. Change only automatic context passing. Measure actual exposed usage separately from estimates and include summarization and re-explanation costs.

## Reproduction steps

To establish the current gap, inspect scripts/benchmark_context.py: synthetic stored records and packet-size measurements are not a two-tool session experiment.

Prescribed test procedure:

1. Create disposable worktrees/vaults and a synthetic task fixture containing a goal, decisions, a correction, completed work, changed files, a failing test and unfinished next steps. Define answerable fact checks and executable completion tests before running either arm. Never use the real vault or personal sessions.
2. Run a source-tool session to a fixed handoff point and snapshot its changed files, conversation/evidence and usage. Reuse this exact source state for both arms. Simulate the source becoming unavailable; do not wait for a real quota limit.
3. Arm OFF: launch a fresh destination session with the source's resulting files but no automatic handoff packet or shared memory access. Give the same minimal continuation request.
4. Arm ON: launch the same destination tool/model/settings from an identical snapshot and fresh session, with automatic checkpoint/context passing enabled. Give the identical continuation request. Do not paste a summary manually.
5. In both arms, use the same deterministic responder with the fixture's factual answer bank if the tool asks for clarification. Count every clarification/re-explanation token. Mark an unanswered/failed task as failure rather than giving one arm a secret advantage.
6. Collect per-request usage when exposed: source input/output, destination input/output, cached input, compaction, local summarization, injected packet and clarification text. Keep host-reported usage, named-tokenizer counts and character-based estimates in separate columns. Unavailable counters remain unavailable, not zero.
7. Run executable task tests and a predeclared checklist of retained decisions, constraints, corrections and next steps. Record repeated work, completion, latency and checkpoint freshness. Use deterministic scoring where possible; disclose any human/LLM judging and its cost.
8. Repeat at least five paired runs for each of three task types (feature work, debugging with a correction, interrupted multi-step work) in both directions: 30 pairs / 60 destination sessions. Alternate or randomize ON/OFF ordering; isolate caches where supported, otherwise record cache status. Pin tool/model versions, task seeds and settings.
9. Generate a machine-readable results file and human-readable report automatically. Report each direction/task plus aggregate median and spread; do not cherry-pick the best run. Save sanitized fixtures, configuration and commands so the benchmark is repeatable.

## Acceptance criteria

- [ ] An automated command runs both cross-tool directions and both ON/OFF arms without manual session saving, restoring or re-explanation.
- [ ] At least 30 matched pairs as prescribed, or an explicit incomplete/blocked result naming missing access; replay-only tests are not called live two-tool verification.
- [ ] Report absolute and percentage savings for destination-stage tokens and for the whole workflow, including checkpoint/summary generation overhead. Keep local-model tokens separate from cloud billed usage.
- [ ] Formula: savings = OFF - ON; savings percent = 100 * (OFF - ON) / OFF. Report negative savings; use N/A when OFF is zero or comparable usage is unavailable.
- [ ] Do not blindly add counts from different tokenizers and call them equivalent: give per-tool usage plus a common named-tokenizer text-volume comparison. Report cost only with separately verified prices, if desired.
- [ ] Both arms receive identical task state and success criteria. Publish completion/fact-retention rates and failures alongside savings; lower token use with worse task correctness is not a pass.
- [ ] Evidence supports positive median end-to-end savings without a lower completion or essential-fact retention rate in the measured suite before claiming demonstrated token savings. Otherwise report no demonstrated benefit and keep this gate open.
- [ ] CI runs no-paid-call replay/regression tests; live runs are opt-in using already authorized clients/accounts and a predeclared run/token ceiling. No unapproved account charges or live private-vault data.
- [ ] Versioned report includes configurations, actual/estimated/unavailable counter flags, repeated work, checkpoint age, latency and uncertainty. No universal saving percentage is advertised.

## Implementation details

Planned, not implemented. Depends on linked checkpoints #57, worker #58, scoped context #56 and automatic handoff #59. Parent #61. Extend the evaluation tooling; keep existing context-size benchmark as a quick component check, not a substitute for this experiment.

Implement deterministic fixture/replay harness alongside the handoff code, then perform actual-client paired runs when the adapters work. Set the live-run budget once at setup; no per-session manual triggers are required. The cost of the common source prefix cancels in the paired difference but must still be included when reporting whole-session percentage savings.

## Verification results

Acceptance design added at the user's explicit request on 2026-09-07. No matched two-tool benchmark has been run and no token-saving number is available. Existing unit-test and packet-size results do not satisfy this gate.

