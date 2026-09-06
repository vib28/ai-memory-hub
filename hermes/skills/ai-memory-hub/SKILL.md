---
name: ai-memory-hub
description: "Use when an AI Memory Hub vault is connected."
version: 0.1.0
author: Hermes Agent + vib28
license: Apache-2.0
platforms: [windows]
---

# AI Memory Hub (Hermes client)

This profile is connected to an **AI Memory Hub** MCP server. Its tools appear as `mcp_ai_memory_hub_*`. The Obsidian Markdown vault behind it is the canonical source of durable user context, shared across every AI tool the user runs (Claude, Codex, Gemini, ChatGPT, Hermes, ...).

Do NOT confuse it with Hermes' native `memory` tool. Hermes' own store is a separate, small curated profile. AI Memory Hub is the larger, shared, governed vault.

## Available tools

- `mcp_ai_memory_hub_memory_policy` — retention policy + current write mode
- `mcp_ai_memory_hub_memory_search` — search the vault (semantic+keyword over SQLite index)
- `mcp_ai_memory_hub_memory_read` — read exactly one memory Markdown file (path must be inside vault)
- `mcp_ai_memory_hub_memory_propose` — validate + store/queue a durable memory
- `mcp_ai_memory_hub_memory_supersede` — replace an existing memory (by stable ID)
- `mcp_ai_memory_hub_memory_forget` — delete one memory by stable ID
- `mcp_ai_memory_hub_memory_audit` — integrity check (no writes)
- `mcp_ai_memory_hub_memory_reindex` — rebuild SQLite index from Markdown

## Retrieval

When the current request could materially benefit from personal history, prior project decisions, durable preferences, people, or recurring constraints:

1. call `mcp_ai_memory_hub_memory_search` with a narrow query
2. call `mcp_ai_memory_hub_memory_read` only for a file that is clearly relevant
3. do not scan the whole vault
4. prefer current explicit user statements over older memory

Do not retrieve memory merely to make an answer feel personalized.

## Proposing and updating

When proposing or superseding, use a concise, stable, hyphenated `subject` (e.g. `primary-development-os`) and reuse it for later facts about the same thing. Let the server choose the canonical path unless a custom path is intentionally required.

- `profile` and `preference`: one subject = one current answer. Supersede only an explicitly replaced fact.
- `project`, `person`, `topic`, `decision`: cumulative logs. Distinct facts may share a subject without superseding each other. A conflict is a review signal, not proof the newest entry is correct.

## Automatic storage

The user does not need to say "remember this." Silently notice durable memories; at a natural boundary propose only the strongest.

Store only: durable user-stated facts, durable preferences, explicit decisions, long-running project constraints/status, important purchases affecting future recommendations, meaningful unresolved questions.

Do NOT store: secrets/identifiers, transient state, search results/prices/news, generated code or your own suggestions, temporary bugs, uncertain inference, sensitive attributes inferred from context. `inferred` candidates are rejected by the server.

Use `mcp_ai_memory_hub_memory_supersede` when the user clearly changes an existing fact and you know its ID. If the user says not to save something, do not propose it. If asked to forget, search narrowly and `mcp_ai_memory_hub_memory_forget` the relevant ID. Do not announce every automatic write unless useful.

## Write mode awareness

Check `mcp_ai_memory_hub_memory_policy` if unsure of the mode. In **review** mode proposals are queued, not stored — tell the user a memory awaits approval in the dashboard when it is useful, and do not claim it was saved. In **auto** mode valid proposals write immediately.

Writer identity for this client: `hermes`.
