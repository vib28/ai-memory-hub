"""Automatic vault health issue remediation.

Surfaces fixable audit findings, creates a GitHub issue for each using the
seven-level format, stores the issue reference in the vault under
``.ai-memory-hub/issues/``, and applies the automatic fix when the user
clicks "Fix" in the dashboard.

Issue types handled:
- ``malformed_memory_lines``: raw browser-automation payloads that leaked
  into a Markdown file as a ``- [...]`` line but fail the ENTRY_RE grammar.
- ``orphan_session_blocks``: ``## <slug>`` heading blocks missing the
  ``<!-- session:<id> -->`` marker, so they are unindexed and undeletable.
- ``duplicate_ids``: the same memory ID appears in more than one file.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from pathlib import Path
from typing import Any, Callable

from .utils import atomic_write, file_lock, slugify, utc_timestamp
from .vault import SESSION_ID_RE, SESSION_RE, dump_frontmatter, parse_frontmatter

logger = logging.getLogger(__name__)

# Patterns that indicate a raw browser-automation payload leaked into the vault.
# These are JSON arrays of ``{"text": ..., "type": "text"}`` objects — the shape
# the Hermes browser tool emits — which have no business in a memory file.
_BROWSER_PAYLOAD_RE = re.compile(
    r'^\s*-\s+\[\s*\{\s*"text"\s*:\s*"[^"]*(?:screenshot|clicked|captured|browser|'
    r'executed|selector|viewport|navigated|successfully)\b[^"]*",\s*'
    r'"type"\s*:\s*"text"',
    re.IGNORECASE,
)

_ISSUES_DIRNAME = ".ai-memory-hub"
_ISSUES_SUBDIR = "issues"


def issues_dir(vault: Path | str) -> Path:
    """Return the directory where auto-fix issue records are stored."""
    root = Path(vault).expanduser().resolve()
    return root.parent / _ISSUES_DIRNAME / _ISSUES_SUBDIR


def _issue_record_path(vault: Path | str, issue_id: str) -> Path:
    """Return the path to a single issue's JSON record."""
    directory = issues_dir(vault)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{issue_id}.json"


def _new_issue_id() -> str:
    return f"fix-{utc_timestamp().replace(':', '').replace('-', '').replace('+', '')[:18]}-{secrets.token_hex(4)}"


def _classify_malformed_line(text: str) -> str:
    """Return a stable issue-type tag for a malformed memory line."""
    if _BROWSER_PAYLOAD_RE.match(text):
        return "browser-payload-leak"
    if text.strip().startswith("- [{"):
        return "malformed-bracket-entry"
    if re.match(r"^\s*-\s+\[", text):
        return "malformed-list-entry"
    return "malformed-line"


def scan_audit_issues(manager) -> list[dict[str, Any]]:
    """Expand manager.audit() findings into individual fixable issue dicts.

    Each issue carries a stable ``issue_type`` so the fix path can dispatch
    without re-inspecting the vault, plus enough context (path, line, text)
    for both the GitHub issue body and the fix logic.
    """
    audit = manager.audit()
    issues: list[dict[str, Any]] = []

    for item in audit.get("malformed_memory_lines", []):
        issue_type = _classify_malformed_line(item.get("text", ""))
        issues.append({
            "issue_id": None,
            "issue_type": issue_type,
            "severity": "warning",
            "summary": f"Malformed memory line in {item['path']} (line {item['line']})",
            "path": item["path"],
            "line": item["line"],
            "text": item["text"],
            "fixable": True,
        })

    for item in audit.get("orphan_session_blocks", []):
        issues.append({
            "issue_id": None,
            "issue_type": "orphan-session-block",
            "severity": "info",
            "summary": f"Orphan session block in {item['path']} (heading '{item['heading']}')",
            "path": item["path"],
            "heading": item["heading"],
            "fixable": True,
        })

    for memory_id in audit.get("duplicate_ids", []):
        issues.append({
            "issue_id": None,
            "issue_type": "duplicate-memory-id",
            "severity": "error",
            "summary": f"Duplicate memory ID: {memory_id}",
            "memory_id": memory_id,
            "fixable": False,
        })

    for memory_id in audit.get("missing_from_index", []):
        issues.append({
            "issue_id": None,
            "issue_type": "missing-from-index",
            "severity": "warning",
            "summary": f"Memory in file but not in index: {memory_id}",
            "memory_id": memory_id,
            "fixable": True,
        })

    for memory_id in audit.get("stale_in_index", []):
        issues.append({
            "issue_id": None,
            "issue_type": "stale-index-entry",
            "severity": "warning",
            "summary": f"Stale index entry (file missing): {memory_id}",
            "memory_id": memory_id,
            "fixable": True,
        })

    return issues


def _build_issue_body(issue: dict[str, Any]) -> str:
    """Render the seven-level GitHub issue body for a fixable audit finding.

    Seven-level format:
    1. Summary
    2. Affected file / location
    3. Evidence (raw text, line content)
    4. Classification (issue type, severity)
    5. Proposed fix
    6. Risks / trade-offs
    7. References
    """
    lines = [
        "## 1. Summary",
        "",
        issue["summary"],
        "",
        "## 2. Affected location",
        "",
        f"- **Path:** `{issue.get('path', 'N/A')}`",
    ]
    if issue.get("line"):
        lines.append(f"- **Line:** {issue['line']}")
    if issue.get("heading"):
        lines.append(f"- **Heading:** `{issue['heading']}`")
    if issue.get("memory_id"):
        lines.append(f"- **Memory ID:** `{issue['memory_id']}`")
    lines += [
        "",
        "## 3. Evidence",
        "",
    ]
    if issue.get("text"):
        lines.append(f"```\n{issue['text'][:500]}\n```")
    else:
        lines.append("_No raw text captured; structural finding._")
    lines += [
        "",
        "## 4. Classification",
        "",
        f"- **Issue type:** `{issue['issue_type']}`",
        f"- **Severity:** {issue['severity']}",
        f"- **Auto-fixable:** {'yes' if issue['fixable'] else 'no'}",
        "",
        "## 5. Proposed fix",
        "",
    ]
    fix_descriptions = {
        "browser-payload-leak": "Delete the malformed `- [...]` line. It is a raw browser-automation payload that leaked into the vault and is not a valid memory entry.",
        "malformed-bracket-entry": "Delete or rewrite the line so it matches the memory entry grammar (`- [tag] text <!-- mem:... source:... date:... -->`).",
        "malformed-list-entry": "Delete the malformed list line; it does not conform to the memory entry format.",
        "orphan-session-block": "Delete the orphan `## <slug>` heading block. Without a `<!-- session:<id> -->` marker it is unindexed, unsearchable, and undeletable through the dashboard.",
        "missing-from-index": "Re-run vault reindex so the in-file memory is picked up by the search index.",
        "stale-index-entry": "Re-run vault reindex so the stale entry (no corresponding file) is purged from the index.",
        "duplicate-memory-id": "Manual review required. Two files contain the same memory ID; one must be renumbered to restore uniqueness.",
    }
    lines.append(fix_descriptions.get(issue["issue_type"], "Manual review required."))
    lines += [
        "",
        "## 6. Risks / trade-offs",
        "",
    ]
    if issue["issue_type"] in {"browser-payload-leak", "malformed-bracket-entry",
                                "malformed-list-entry", "orphan-session-block"}:
        lines.append("- The fix deletes content. Deleted content is recoverable from version control if the vault is git-tracked.")
    elif issue["issue_type"] in {"missing-from-index", "stale-index-entry"}:
        lines.append("- Reindexing is non-destructive; it rebuilds the search index from the canonical Markdown files.")
    else:
        lines.append("- Manual intervention required; no automatic risk.")
    lines += [
        "",
        "## 7. References",
        "",
        f"- Generated by AI Memory Hub auto-fix at {utc_timestamp()}",
        f"- Audit finding key: `{issue['issue_type']}`",
    ]
    return "\n".join(lines)


def build_issue_title(issue: dict[str, Any]) -> str:
    """Return a concise GitHub issue title for a fixable audit finding."""
    return f"[auto-fix] {issue['issue_type']}: {issue.get('summary', 'vault issue')}"


def _create_github_issue(issue: dict[str, Any], repo: str | None = None,
                         client_factory: Callable | None = None) -> dict[str, Any]:
    """Create a GitHub issue for the given audit finding.

    Returns a dict with ``html_url``, ``number``, ``marker``. If GitHub is
    not configured or the call fails, returns a dict with ``skipped: true``
    and ``reason`` so the caller can still record the local issue reference.
    """
    configured_repo = repo or _configured_repo_from_vault(issue)
    if not configured_repo:
        return {"skipped": True, "reason": "no GitHub repository configured"}

    title = build_issue_title(issue)
    body = _build_issue_body(issue)
    marker = f"ai-memory-hub:fix:{issue['issue_type']}:{slugify(issue.get('summary', ''))[:60]}"
    body = f"<!-- {marker} -->\n\n{body}"

    try:
        from .github_export import GitHubClient
        client = client_factory() if client_factory else GitHubClient(configured_repo)
        created = client.create_issue(title, body)
        return {
            "html_url": created["html_url"],
            "number": created["number"],
            "marker": marker,
            "skipped": False,
        }
    except Exception as exc:
        logger.warning("Failed to create GitHub issue for %s: %s", issue["summary"], exc)
        return {"skipped": True, "reason": f"GitHub issue creation failed: {exc}"}


def _configured_repo_from_vault(issue: dict[str, Any]) -> str | None:
    """Try to find a configured GitHub repo for the vault (best-effort)."""
    vault = issue.get("vault_path")
    if not vault:
        return None
    try:
        from .github_export import load_config
        from .vault import Vault
        root = Vault(Path(vault)).root
        config = load_config(root)
        return config.get("repo") if config.get("enabled") else None
    except Exception:
        return None


def record_issue(vault: Path | str, issue: dict[str, Any], github: dict[str, Any] | None = None) -> str:
    """Persist an issue record to the vault's .ai-memory-hub/issues/ directory.

    Returns the stable issue_id used as the file name.
    """
    issue_id = issue.get("issue_id") or _new_issue_id()
    record = {
        "issue_id": issue_id,
        "created_at": utc_timestamp(),
        "issue_type": issue["issue_type"],
        "severity": issue["severity"],
        "summary": issue["summary"],
        "path": issue.get("path"),
        "line": issue.get("line"),
        "text": issue.get("text"),
        "heading": issue.get("heading"),
        "memory_id": issue.get("memory_id"),
        "fixable": issue.get("fixable", False),
        "fixed": False,
        "fixed_at": None,
        "github": github or {"skipped": True, "reason": "not attempted"},
    }
    target = _issue_record_path(vault, issue_id)
    with file_lock(target):
        atomic_write(target, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return issue_id


def _mark_issue_fixed(vault: Path | str, issue_id: str, github: dict[str, Any] | None = None) -> None:
    """Update an existing issue record to mark it as fixed."""
    target = _issue_record_path(vault, issue_id)
    if not target.exists():
        return
    with file_lock(target):
        record = json.loads(target.read_text(encoding="utf-8"))
        record["fixed"] = True
        record["fixed_at"] = utc_timestamp()
        if github is not None:
            record["github"] = github
        atomic_write(target, json.dumps(record, ensure_ascii=False, indent=2) + "\n")


def _delete_malformed_line(vault_root: Path, path: str, line: int) -> bool:
    """Delete a single malformed line from a Markdown file.

    ``line`` is 1-indexed to match the audit output. Returns True if the line
    was removed, False if it was already gone or did not match expectations.
    """
    from .vault import Vault
    p = Vault(vault_root).resolve(path)
    if not p.exists():
        return False
    with file_lock(p):
        content = p.read_text(encoding="utf-8")
        lines = content.splitlines()
        if line < 1 or line > len(lines):
            return False
        target_idx = line - 1
        # Guard: only remove lines that look like malformed bracket entries
        # (defensive -- never silently delete a well-formed memory line).
        if not re.match(r"^\s*-\s+\[", lines[target_idx]):
            return False
        del lines[target_idx]
        atomic_write(p, "\n".join(lines) + "\n")
    return True


def _delete_orphan_session_block(vault_root: Path, path: str, heading: str) -> bool:
    """Remove an orphan ``## <slug>`` session block from a session file."""
    from .vault import Vault
    vault = Vault(vault_root)
    p = vault.resolve(path)
    if not p.exists():
        return False
    with file_lock(p):
        content = p.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(content)
        matches = list(SESSION_RE.finditer(body))
        if not matches:
            return False
        # Content above the first heading (a user's own preamble note, or a
        # malformed/missing frontmatter block) is outside every match and was
        # silently dropped on rewrite -- same guard as orphan_session_blocks.
        preamble = body[:matches[0].start()].strip("\n") if matches else ""
        kept: list[str] = []
        removed = False
        for block in matches:
            slug = block.group("slug")
            has_marker = SESSION_ID_RE.search(block.group("body")) is not None
            if slug == heading and not has_marker:
                removed = True
                continue
            kept.append(block.group(0).rstrip())
        if not removed:
            return False
        rebuilt = dump_frontmatter(meta) if meta else ""
        if preamble:
            rebuilt += ("\n" if rebuilt else "") + preamble + "\n"
        if kept:
            rebuilt += ("\n" if rebuilt else "") + "\n\n".join(kept) + "\n"
        atomic_write(p, rebuilt)
    return True


def apply_fix(manager, issue: dict[str, Any]) -> dict[str, Any]:
    """Apply the automatic fix for a single issue.

    Returns a dict with ``status`` and a human-readable ``message``.
    Does not reindex -- the caller is responsible for that afterward.
    """
    issue_type = issue["issue_type"]
    vault_root = manager.vault.root

    if issue_type in {"browser-payload-leak", "malformed-bracket-entry",
                      "malformed-list-entry", "malformed-line"}:
        path = issue.get("path")
        line = issue.get("line")
        if not path or not line:
            return {"status": "failed", "message": "Missing path/line for malformed-line fix"}
        if _delete_malformed_line(vault_root, path, line):
            return {"status": "fixed", "message": f"Removed malformed line {line} from {path}"}
        return {"status": "skipped", "message": "Line was already gone or did not match safety check"}

    if issue_type == "orphan-session-block":
        path = issue.get("path")
        heading = issue.get("heading")
        if not path or not heading:
            return {"status": "failed", "message": "Missing path/heading for orphan-session fix"}
        if _delete_orphan_session_block(vault_root, path, heading):
            return {"status": "fixed", "message": f"Removed orphan session block '{heading}' from {path}"}
        return {"status": "skipped", "message": "Orphan block was already gone"}

    if issue_type == "missing-from-index":
        # Reindex picks up in-file memories that were missed.
        count = manager.reindex()
        return {"status": "fixed", "message": f"Reindexed vault ({count} records)"}

    if issue_type == "stale-index-entry":
        # Reindex purges stale entries because _all_records only reads real files.
        count = manager.reindex()
        return {"status": "fixed", "message": f"Reindexed vault ({count} records)"}

    if issue_type == "duplicate-memory-id":
        return {"status": "manual", "message": "Duplicate memory IDs require manual review to choose which file keeps the ID."}

    return {"status": "unhandled", "message": f"No fix implemented for issue type: {issue_type}"}


def fix_issue(manager, issue_type: str, summary: str, **kwargs) -> dict[str, Any]:
    """Top-level entry point for the dashboard's POST /api/fix-issue endpoint.

    Builds the issue dict, creates a GitHub issue (best-effort), records it in
    the vault, applies the fix (if fixable), and updates the record. Returns
    a dict suitable for JSON serialization to the dashboard frontend.
    """
    issue: dict[str, Any] = {
        "issue_id": None,
        "issue_type": issue_type,
        "severity": kwargs.get("severity", "warning"),
        "summary": summary,
        "fixable": kwargs.get("fixable", False),
        "vault_path": str(manager.vault.root),
        **kwargs,
    }

    # Step 1: Attempt to create a GitHub issue (best-effort, non-blocking).
    github_result = _create_github_issue(issue)

    # Step 2: Record the issue in the vault (always, even if GitHub failed).
    issue_id = record_issue(manager.vault.root, issue, github_result)

    # Step 3: Apply the fix if the issue is auto-fixable.
    fix_result = {"status": "skipped", "message": "Not auto-fixable"}
    if issue.get("fixable"):
        fix_result = apply_fix(manager, issue)
        if fix_result["status"] in {"fixed", "manual"}:
            _mark_issue_fixed(manager.vault.root, issue_id, github_result)

    return {
        "issue_id": issue_id,
        "github": github_result,
        "fix": fix_result,
        "issue": {**issue, "issue_id": issue_id},
    }
