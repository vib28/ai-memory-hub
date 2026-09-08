"""Opt-in, sanitized GitHub issue export for accepted local checkpoints.

Local Markdown and the checkpoint manifest remain canonical.  This module only
publishes accepted, structured session sections through a durable SQLite outbox;
capture and startup handoff never call it synchronously.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .handoff import _manifest, _read_block
from .security import SECRET_PATTERNS, check_text
from .utils import atomic_write, slugify


VISIBILITIES = {"public", "private", "internal"}
DEFAULT_INTERVAL_SECONDS = 30
MAX_RETRY_SECONDS = 300
_PRIVATE_PATH_RE = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\|/(?:users|home|private|tmp|var)/)[^\s,;]+")
_URL_RE = re.compile(r"https://github\.com/[^\s]+/issues/(\d+)(?:#issuecomment-(\d+))?")


class ExportError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _vault_key(vault: Path | str) -> str:
    return hashlib.sha256(str(Path(vault).expanduser().resolve()).encode("utf-8")).hexdigest()[:16]


def config_path(vault: Path | str) -> Path:
    configured = os.environ.get("MEMORY_GITHUB_EXPORT_CONFIG", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".ai-memory-hub" / f"github-export-{_vault_key(vault)}.json"


def outbox_path(vault: Path | str) -> Path:
    configured = os.environ.get("MEMORY_GITHUB_OUTBOX", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".ai-memory-hub" / f"github-outbox-{_vault_key(vault)}.sqlite3"


def health_path(vault: Path | str) -> Path:
    configured = os.environ.get("MEMORY_GITHUB_HEALTH", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".ai-memory-hub" / f"github-export-health-{_vault_key(vault)}.json"


def load_config(vault: Path | str) -> dict[str, Any]:
    path = config_path(vault)
    if not path.exists():
        return {"enabled": False, "configured": False, "config_path": str(path)}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"GitHub export configuration is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise ExportError("GitHub export configuration must be an object")
    value["config_path"] = str(path)
    return value


def configure(vault: Path | str, *, repo: str | None = None, visibility: str | None = None,
              enabled: bool) -> dict[str, Any]:
    path = config_path(vault)
    current = load_config(vault)
    if enabled:
        repo = (repo or current.get("repo") or "").strip()
        visibility = (visibility or current.get("visibility") or "").strip().lower()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ExportError("--repo must be an owner/name GitHub repository")
        if visibility not in VISIBILITIES:
            raise ExportError("--visibility must be public, private or internal")
    else:
        repo = str(current.get("repo") or repo or "")
        visibility = str(current.get("visibility") or visibility or "")
    value = {
        "version": 1,
        "enabled": bool(enabled),
        "approved": bool(enabled),
        "repo": repo,
        "visibility": visibility,
        "approved_at": _stamp(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return {**value, "config_path": str(path)}


def _one_line(value: Any, limit: int = 1000) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())[:limit]


def _items(value: Any, limit: int = 30) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_one_line(item) for item in value if _one_line(item)][:limit]


def _safe_text(value: Any, limit: int = 1000) -> str:
    text = _one_line(value, limit)
    text = _PRIVATE_PATH_RE.sub("[private path redacted]", text)
    for pattern, _label in SECRET_PATTERNS:
        text = pattern.sub("[redacted sensitive evidence]", text)
    return text if check_text(text).safe else "[redacted sensitive content]"


def _safe_path(value: Any) -> str:
    text = _one_line(value, 500).replace("\\", "/")
    if not text or _PRIVATE_PATH_RE.match(text) or text.startswith("/"):
        return "[private path redacted]"
    return text


def _marker(group_id: str, checkpoint_id: str) -> str:
    return f"ai-memory-hub:checkpoint:{slugify(group_id)}:{slugify(checkpoint_id)}"


def _group_marker(group_id: str) -> str:
    return f"ai-memory-hub:group:{slugify(group_id)}"


def build_export_payloads(vault: Path | str, group_id: str | None = None) -> list[dict[str, Any]]:
    root = Path(vault).expanduser().resolve()
    manifest, warning = _manifest(root)
    if manifest is None:
        raise ExportError(warning or "checkpoint manifest is unavailable")
    payloads: list[dict[str, Any]] = []
    for raw_group_id, raw_group in manifest.get("groups", {}).items():
        current_group_id = str(raw_group_id)
        if group_id and current_group_id != group_id:
            continue
        if not isinstance(raw_group, dict):
            continue
        entries = [entry for entry in raw_group.get("entries", []) if isinstance(entry, dict)]
        for entry in sorted(entries, key=lambda item: (int(item.get("sequence", 0) or 0), str(item.get("checkpoint_id") or ""))):
            if str(entry.get("state") or "accepted") != "accepted":
                continue
            block, _body = _read_block(root, entry)
            if not block:
                raise ExportError(f"checkpoint block is missing: {entry.get('checkpoint_id')}")
            metadata = block.get("metadata") if isinstance(block.get("metadata"), dict) else {}
            checkpoint_id = _one_line(entry.get("checkpoint_id"), 200)
            payloads.append({
                "marker": _marker(current_group_id, checkpoint_id),
                "group_marker": _group_marker(current_group_id),
                "session_group_id": current_group_id,
                "checkpoint_id": checkpoint_id,
                "sequence": int(entry.get("sequence", 0) or 0),
                "entry_type": _one_line(entry.get("entry_type") or "checkpoint", 30),
                "state": "accepted",
                "project": _safe_text(raw_group.get("project") or entry.get("project"), 200) or None,
                "source_client": _safe_text(raw_group.get("source_client") or entry.get("source_client") or "unknown", 100),
                "title": _safe_text(block.get("title") or "Session checkpoint", 300),
                "date": _safe_text(block.get("date"), 80),
                "investigated": [_safe_text(item) for item in _items(block.get("investigated"))],
                "learned": [_safe_text(item) for item in _items(block.get("learned"))],
                "completed": [_safe_text(item) for item in _items(block.get("completed"))],
                "next_steps": [_safe_text(item) for item in _items(block.get("next_steps"))],
                "changed_files": [_safe_path(item) for item in _items(entry.get("changed_files") or metadata.get("changed_files"), 100)],
                "previous_marker": _marker(current_group_id, entry["previous_id"]) if entry.get("previous_id") else None,
                "next_marker": _marker(current_group_id, entry["next_id"]) if entry.get("next_id") else None,
                "final_marker": _marker(current_group_id, entry["final_id"]) if entry.get("final_id") else None,
            })
    return payloads


def _link(marker: str | None, links: dict[str, str]) -> str:
    return links.get(marker or "", marker or "none")


def render_comment(payload: dict[str, Any], links: dict[str, str] | None = None) -> str:
    links = links or {}
    lines = [
        f"<!-- {payload['marker']} -->",
        f"## {payload['entry_type'].title()} {payload['sequence']}: {payload['title']}",
        f"**Project:** {payload.get('project') or 'None'}  ",
        f"**Source client:** {payload['source_client']}  ",
        f"**Date:** {payload.get('date') or 'unknown'}  ",
        f"**Checkpoint:** `{payload['checkpoint_id']}`  ",
        f"**State:** `{payload['state']}`",
        "",
    ]
    for heading, key in (("Investigated", "investigated"), ("Learned", "learned"),
                         ("Completed", "completed"), ("Next Steps", "next_steps")):
        lines.append(f"### {heading}")
        values = payload.get(key) or []
        lines.extend(f"- {item}" for item in values) if values else lines.append("- (none recorded)")
        lines.append("")
    files = payload.get("changed_files") or []
    lines.append("**Changed files:** " + (", ".join(files) if files else "none recorded"))
    lines.append(f"**Previous:** {_link(payload.get('previous_marker'), links)}")
    lines.append(f"**Next:** {_link(payload.get('next_marker'), links)}")
    lines.append(f"**Final:** {_link(payload.get('final_marker'), links)}")
    return "\n".join(lines).rstrip() + "\n"


def _replace_owned_block(text: str, begin: str, end: str, block: str) -> str:
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    owned = block.rstrip() if block.lstrip().startswith(begin) else f"{begin}\n{block.rstrip()}\n{end}"
    if pattern.search(text):
        return pattern.sub(owned, text, count=1)
    return (text.rstrip() + "\n\n" if text.strip() else "") + owned + "\n"


def render_issue_block(group_id: str, payloads: list[dict[str, Any]], links: dict[str, str]) -> str:
    project = next((item.get("project") for item in payloads if item.get("project")), None) or "unscoped"
    lines = [
        f"<!-- {_group_marker(group_id)} -->",
        "# AI Memory Hub session log",
        "",
        "This is a sanitized publication mirror of accepted local checkpoint summaries. "
        "The local Markdown vault remains canonical; this issue is not a raw transcript.",
        "",
        f"**Project:** {project}  ",
        f"**Work group:** `{_safe_text(group_id, 200)}`",
        f"**Tags:** `#ai-memory-session` `#group-{slugify(group_id)}` `#project-{slugify(str(project))}`",
        "",
        "| Sequence | Entry | Checkpoint | State | Comment |",
        "|---:|---|---|---|---|",
    ]
    for payload in payloads:
        url = links.get(payload["marker"], payload["marker"])
        lines.append(f"| {payload['sequence']} | {payload['entry_type']} | `{payload['checkpoint_id']}` | {payload['state']} | [open]({url}) |" if url.startswith("http") else f"| {payload['sequence']} | {payload['entry_type']} | `{payload['checkpoint_id']}` | {payload['state']} | `{url}` |")
    lines.extend(["", "<!-- ai-memory-hub:group-end -->"])
    return "\n".join(lines)


class ExportOutbox:
    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS exports (
            marker TEXT PRIMARY KEY,
            session_group_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT,
            lease_owner TEXT,
            lease_expires_at TEXT,
            remote_issue_number INTEGER,
            remote_comment_id INTEGER,
            remote_comment_url TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_exports_due ON exports(status, next_attempt_at);
        CREATE INDEX IF NOT EXISTS idx_exports_group ON exports(session_group_id, status);
        """)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        stamp = _stamp()
        with self.conn:
            self.conn.execute(
                """INSERT OR IGNORE INTO exports
                (marker,session_group_id,payload_json,created_at,updated_at)
                VALUES (?,?,?,?,?)""",
                (payload["marker"], payload["session_group_id"], json.dumps(payload, ensure_ascii=False), stamp, stamp),
            )
        row = self.conn.execute("SELECT * FROM exports WHERE marker=?", (payload["marker"],)).fetchone()
        return dict(row)

    def due_groups(self, now: datetime | None = None) -> list[str]:
        stamp = _stamp(now)
        rows = self.conn.execute(
            """SELECT DISTINCT session_group_id FROM exports
               WHERE status IN ('pending','failed') AND (next_attempt_at IS NULL OR next_attempt_at<=?)
               ORDER BY session_group_id""", (stamp,)
        )
        return [str(row[0]) for row in rows]

    def claim_group(self, group_id: str, *, owner: str, now: datetime | None = None) -> list[dict[str, Any]]:
        clock = now or _now()
        stamp = _stamp(clock)
        lease = _stamp(clock + timedelta(minutes=5))
        with self.conn:
            self.conn.execute(
                "UPDATE exports SET status='pending', lease_owner=NULL, lease_expires_at=NULL "
                "WHERE session_group_id=? AND status='processing' AND lease_expires_at<?",
                (group_id, stamp),
            )
            rows = self.conn.execute(
                """SELECT marker FROM exports WHERE session_group_id=?
                   AND status IN ('pending','failed')
                   AND (next_attempt_at IS NULL OR next_attempt_at<=?)""", (group_id, stamp),
            ).fetchall()
            markers = [str(row[0]) for row in rows]
            if markers:
                self.conn.executemany(
                    "UPDATE exports SET status='processing',lease_owner=?,lease_expires_at=?,attempts=attempts+1,updated_at=? WHERE marker=?",
                    [(owner, lease, stamp, marker) for marker in markers],
                )
        return self.group_rows(group_id)

    def group_rows(self, group_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM exports WHERE session_group_id=? ORDER BY json_extract(payload_json,'$.sequence'), marker", (group_id,)).fetchall()
        return [dict(row) for row in rows]

    def set_remote(self, marker: str, *, issue_number: int, comment_id: int | None, comment_url: str | None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE exports SET remote_issue_number=?,remote_comment_id=?,remote_comment_url=?,updated_at=? WHERE marker=?",
                (issue_number, comment_id, comment_url, _stamp(), marker),
            )

    def mark_sent(self, markers: list[str]) -> None:
        with self.conn:
            self.conn.executemany(
                "UPDATE exports SET status='sent',lease_owner=NULL,lease_expires_at=NULL,last_error=NULL,updated_at=? WHERE marker=?",
                [(_stamp(), marker) for marker in markers],
            )

    def mark_failed(self, markers: list[str], error: str) -> None:
        rows = self.conn.execute("SELECT marker,attempts FROM exports WHERE marker IN (%s)" % ",".join("?" for _ in markers), markers).fetchall() if markers else []
        stamp = _now()
        with self.conn:
            for row in rows:
                delay = min(MAX_RETRY_SECONDS, 2 ** min(int(row["attempts"]), 8))
                self.conn.execute(
                    "UPDATE exports SET status='failed',lease_owner=NULL,lease_expires_at=NULL,last_error=?,next_attempt_at=?,updated_at=? WHERE marker=?",
                    (_one_line(error, 1000), _stamp(stamp + timedelta(seconds=delay)), _stamp(stamp), row["marker"]),
                )

    def health(self) -> dict[str, Any]:
        rows = self.conn.execute("SELECT status,COUNT(*) AS count FROM exports GROUP BY status").fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}


class GitHubClient:
    def __init__(self, repo: str, *, runner: Callable[..., subprocess.CompletedProcess[str]] | None = None):
        self.repo = repo
        self.runner = runner or subprocess.run

    def _run(self, args: list[str]) -> str:
        try:
            result = self.runner(["gh", *args], capture_output=True, text=True, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExportError(f"GitHub command unavailable: {exc}") from exc
        if result.returncode != 0:
            raise ExportError((result.stderr or result.stdout or "GitHub command failed").strip())
        return result.stdout.strip()

    def _api_json(self, endpoint: str) -> Any:
        raw = self._run(["api", endpoint])
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExportError("GitHub returned invalid JSON") from exc

    def repo_visibility(self) -> str:
        value = self._api_json(f"repos/{self.repo}")
        return str(value.get("visibility", "")).lower()

    def find_issue(self, marker: str) -> dict[str, Any] | None:
        value = self._api_json(f"repos/{self.repo}/issues?state=all&per_page=100")
        if not isinstance(value, list):
            return None
        return next((item for item in value if not item.get("pull_request") and marker in str(item.get("body") or "")), None)

    def create_issue(self, title: str, body: str) -> dict[str, Any]:
        raw = self._run(["issue", "create", "--repo", self.repo, "--title", title, "--body", body])
        match = _URL_RE.search(raw)
        if not match:
            raise ExportError("GitHub issue creation returned no issue URL")
        return {"number": int(match.group(1)), "html_url": raw.strip(), "body": body}

    def update_issue(self, number: int, body: str) -> None:
        self._run(["api", f"repos/{self.repo}/issues/{number}", "--method", "PATCH", "-f", f"body={body}"])

    def list_comments(self, number: int) -> list[dict[str, Any]]:
        value = self._api_json(f"repos/{self.repo}/issues/{number}/comments?per_page=100")
        return value if isinstance(value, list) else []

    def create_comment(self, number: int, body: str) -> dict[str, Any]:
        raw = self._run(["issue", "comment", str(number), "--repo", self.repo, "--body", body])
        match = _URL_RE.search(raw)
        if match:
            return {"id": int(match.group(2) or 0), "html_url": raw.strip()}
        raise ExportError("GitHub comment creation returned no comment URL")

    def update_comment(self, comment_id: int, body: str) -> None:
        self._run(["api", f"repos/{self.repo}/issues/comments/{comment_id}", "--method", "PATCH", "-f", f"body={body}"])


class GitHubPublisher:
    def __init__(self, vault: Path | str, *, client: GitHubClient | None = None,
                 outbox: ExportOutbox | None = None):
        self.vault = Path(vault).expanduser().resolve()
        self.config = load_config(self.vault)
        self.outbox = outbox or ExportOutbox(outbox_path(self.vault))
        self._owns_outbox = outbox is None
        self.client = client or GitHubClient(str(self.config.get("repo") or ""))

    def close(self) -> None:
        if self._owns_outbox:
            self.outbox.close()

    def enqueue_accepted(self, group_id: str | None = None) -> dict[str, Any]:
        if not self.config.get("enabled") or not self.config.get("approved"):
            return {"status": "disabled", "enqueued": 0}
        count = 0
        for payload in build_export_payloads(self.vault, group_id):
            self.outbox.enqueue(payload)
            count += 1
        return {"status": "queued", "enqueued": count, "groups": self.outbox.due_groups()}

    def _publish_group(self, group_id: str, claimed: list[dict[str, Any]], owner: str) -> dict[str, Any]:
        all_rows = self.outbox.group_rows(group_id)
        payloads = [json.loads(row["payload_json"]) for row in all_rows]
        group_marker = _group_marker(group_id)
        issue = self.client.find_issue(group_marker)
        if issue is None:
            project = next((item.get("project") for item in payloads if item.get("project")), None) or "unscoped"
            issue = self.client.create_issue(f"AI Memory Hub session: {project}", render_issue_block(group_id, payloads, {}))
        issue_number = int(issue["number"])
        comments = self.client.list_comments(issue_number)
        links: dict[str, str] = {}
        comment_records: dict[str, dict[str, Any]] = {}
        for row, payload in zip(all_rows, payloads):
            marker = payload["marker"]
            existing = next((comment for comment in comments if marker in str(comment.get("body") or "")), None)
            if existing:
                comment_records[marker] = existing
                links[marker] = str(existing.get("html_url") or f"https://github.com/{self.client.repo}/issues/{issue_number}#issuecomment-{existing.get('id')}")
                self.outbox.set_remote(marker, issue_number=issue_number, comment_id=existing.get("id"), comment_url=links[marker])
            else:
                created = self.client.create_comment(issue_number, render_comment(payload))
                comment_records[marker] = created
                links[marker] = str(created.get("html_url") or "")
                self.outbox.set_remote(marker, issue_number=issue_number, comment_id=created.get("id"), comment_url=links[marker])
        issue_body = str(issue.get("body") or "")
        issue_body = _replace_owned_block(issue_body, f"<!-- {group_marker} -->", "<!-- ai-memory-hub:group-end -->", render_issue_block(group_id, payloads, links))
        self.client.update_issue(issue_number, issue_body)
        for payload in payloads:
            record = comment_records[payload["marker"]]
            body = render_comment(payload, links)
            if record.get("id"):
                self.client.update_comment(int(record["id"]), body)
        self.outbox.mark_sent([str(row["marker"]) for row in claimed])
        return {"group": group_id, "issue": issue_number, "comments": len(payloads), "status": "published"}

    def publish_once(self) -> dict[str, Any]:
        if not self.config.get("enabled") or not self.config.get("approved"):
            return {"status": "disabled", "published": 0, "errors": []}
        visibility = str(self.config.get("visibility") or "").lower()
        if visibility not in VISIBILITIES:
            raise ExportError("configured GitHub visibility is invalid")
        # Verify destination approval before the first write; an outage leaves rows queued.
        try:
            actual_visibility = self.client.repo_visibility()
        except Exception as exc:
            return {"status": "degraded", "published": 0, "groups": [],
                    "errors": [{"reason": str(exc)}]}
        if actual_visibility != visibility:
            return {"status": "degraded", "published": 0, "groups": [],
                    "errors": [{"reason": f"approved visibility is {visibility}, GitHub reports {actual_visibility or 'unknown'}"}]}
        published: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for group_id in self.outbox.due_groups():
            owner = uuid.uuid4().hex
            claimed = self.outbox.claim_group(group_id, owner=owner)
            if not claimed:
                continue
            markers = [str(row["marker"]) for row in claimed]
            try:
                published.append(self._publish_group(group_id, claimed, owner))
            except Exception as exc:
                self.outbox.mark_failed(markers, str(exc))
                errors.append({"group": group_id, "reason": str(exc)})
        return {"status": "degraded" if errors else "ok", "published": len(published), "groups": published, "errors": errors}


def write_health(vault: Path | str, value: dict[str, Any]) -> None:
    path = health_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps({**value, "updated_at": _stamp(), "health_path": str(path)}, indent=2) + "\n")


def run_once(vault: Path | str, group_id: str | None = None) -> dict[str, Any]:
    publisher = GitHubPublisher(vault)
    try:
        queued = publisher.enqueue_accepted(group_id)
        if queued["status"] == "disabled":
            result = {"status": "disabled", "queued": 0, "published": 0, "errors": []}
        else:
            result = publisher.publish_once()
            result["queued"] = queued["enqueued"]
        write_health(vault, result)
        return result
    except Exception as exc:
        result = {"status": "degraded", "queued": 0, "published": 0, "errors": [{"reason": str(exc)}]}
        write_health(vault, result)
        return result
    finally:
        publisher.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the opt-in AI Memory Hub GitHub export outbox.")
    parser.add_argument("--vault", default=os.environ.get("AI_MEMORY_VAULT"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--group")
    parser.add_argument("--interval-seconds", type=int, default=int(os.environ.get("MEMORY_GITHUB_EXPORT_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)))
    args = parser.parse_args(argv)
    if not args.vault:
        parser.error("Set --vault or AI_MEMORY_VAULT")
    if args.once:
        print(json.dumps(run_once(args.vault, args.group), ensure_ascii=False))
        return 0
    while True:
        print(json.dumps(run_once(args.vault, args.group), ensure_ascii=False), flush=True)
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
