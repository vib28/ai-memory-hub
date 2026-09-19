# Cold Start Summary

## Context

The user is building **ai-memory-hub v0.2.1** — a local-first shared memory system for AI tools (Claude Code, Codex CLI, Gemini CLI, Qwen Code, Kimi Code, Hermes Agent). The project captures session evidence, consolidates it into Markdown memories, and injects relevant context into new sessions via MCP.

The conversation covered **7 ultrareview cycles** finding and fixing **126+ issues**, **Rust hot path porting** for performance, **browser tool normalization** to fix Hermes payload pollution, **encryption at rest**, **capability health dashboard**, **manual hook system**, **auto-fix system**, and finally **closing all 16 remaining GitHub issues**.

## User Goals and Reasoning

1. **Quality first** — The user insisted on faithful Rust ports (no simplification), 7-level GitHub issue format, and systematic ultrareview until zero findings
2. **Branch discipline** — All work on `enhancements/no-promises`, never `master`
3. **Documentation** — Beautiful GitHub-format docs with tables, badges, mermaid diagrams
4. **No silent failures** — Every fix must have tests; pre-existing flaky tests must be identified
5. **Context capture** — The user identified that browser tool payloads were polluting the vault and demanded a normalizer

## Key Progress and Decisions

| Decision | Rationale |
|----------|-----------|
| Rust via PyO3 with Python fallback | Performance + compatibility |
| Browser normalizer as separate module | Single responsibility, testable |
| `MEMORY_NATIVE_BACKEND` env flag | Graceful degradation |
| AES-256-GCM for encryption | Standard, well-audited |
| 7-level GitHub issue format | Consistency, traceability |
| `select = ["ALL"]` in ruff | Maximum lint coverage |

## Open Threads and Next Actions

- **#62 benchmark** — Research question; scripts available but not automated
- **Cross-tool first-turn proof** — Needs real session in Claude → Codex/Kimi/Qwen/Gemini/Hermes
- **Flaky tests** — 7 pre-existing failures in `test_context_packet.py`, `test_pipeline_e2e.py`, `test_dashboard_features.py`, `test_benchmark_handoff.py`

## Continuation Guidance

The project is on branch `enhancements/no-promises`. All 16 open issues are closed. The Rust crate compiles and loads. 444+ tests pass. To continue: merge to `main` when ready, then tackle the flaky tests or the cross-tool benchmark.
