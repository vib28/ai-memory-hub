"""Canonical event name constants for AI Memory Hub lifecycle events.

Single source of truth for the normalized event names used across the
capture pipeline, consolidation, and transcript modules. Importing these
constants (instead of scattering string literals) prevents drift between
modules that need to agree on event identity.
"""

from __future__ import annotations

# Normalized lifecycle event names (kebab-case).
SESSION_START = "session-start"
SESSION_END = "session-end"
USER_PROMPT_SUBMIT = "user-prompt-submit"
PRE_TOOL_USE = "pre-tool-use"
POST_TOOL_USE = "post-tool-use"
POST_TOOL_USE_FAILURE = "post-tool-use-failure"
PRE_COMPACT = "pre-compact"
POST_COMPACTION = "post-compaction"
STOP = "stop"
STOP_FAILURE = "stop-failure"
INTERRUPT = "interrupt"
SESSION_HEARTBEAT = "session-heartbeat"
SUBAGENT_STOP = "subagent-stop"
OBSERVATION = "observation"

# Events that trigger a detached consolidation after the receiver accepts them.
CONSOLIDATION_EVENTS: frozenset[str] = frozenset({
    SESSION_END,
    STOP,
    STOP_FAILURE,
    INTERRUPT,
    PRE_COMPACT,
    POST_COMPACTION,
})

# Events whose output_summary is expected to carry error evidence.
FAILURE_EVENTS: frozenset[str] = frozenset({
    POST_TOOL_USE_FAILURE,
    STOP_FAILURE,
    INTERRUPT,
})

# Events that constitute user-prompt boundaries.
PROMPT_EVENTS: frozenset[str] = frozenset({
    USER_PROMPT_SUBMIT,
    PRE_TOOL_USE,
})

# Events that constitute agent-stop boundaries.
AFTER_AGENT_EVENTS: frozenset[str] = frozenset({
    STOP,
    SUBAGENT_STOP,
    POST_TOOL_USE,
})

# Host field carrying assistant evidence per event type.
PROMPT_FIELDS = ("prompt", "submitted_prompt", "user_message")
ASSISTANT_FIELDS = ("last_assistant_message", "prompt_response", "response", "final_response")
HOST_META_FIELDS = (
    "transcript_path", "model", "permission_mode", "client_type", "source",
    "reason", "trigger", "error_type", "error_message", "agent_type", "agent_id",
    "stop_hook_active", "turn_id", "session_title", "profile", "platform",
    "uptime_ms", "token_count", "estimated_token_count", "custom_instructions",
)
