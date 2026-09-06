# Contributing

Keep accepted memories readable, changes reviewable and evidence honest.

[Architecture](ARCHITECTURE.md) · [Roadmap](docs/local-memory-plan.md) · [Documentation](docs/README.md)

## Development environment

From the repository root:

~~~powershell
uv sync --locked --extra dev
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ty.exe check
~~~

Use a new disposable test directory if the existing pytest temporary root is inaccessible;
see [troubleshooting](docs/TROUBLESHOOTING.md#tests-cannot-create-a-temporary-directory).

The current CI workflow runs on pushes to master and pull requests, with Windows/Ubuntu
and Python 3.10–3.12. It does not run on every enhancement-branch push. Type checking is
advisory. Ruff checks the configured rule set; it does not prove runtime correctness
or client integration.

## Issue workflow

For each discovered bug:

1. Create or update a GitHub issue before implementing a fix.
2. Record reproduction steps and acceptance criteria.
3. Implement the scoped fix.
4. Test locally with synthetic data.
5. Add a detailed implementation and verification comment.
6. Close only after the acceptance criteria have been verified.

Issues and roadmap entries use these exact sections, in plain language:

- Where the problem exists.
- Why it matters.
- How the fix works.
- Reproduction steps.
- Acceptance criteria.
- Implementation details.
- Verification results.

State when evidence is unavailable. Do not infer a historical test result or close
an issue because a design document exists.

## Safety boundaries

- Keep secrets and real personal vault content out of issues, fixtures and commits.
- Preserve unrelated worktree changes and client settings.
- Client-facing memory proposals use the public MCP policy boundary.
- Test registered MCP error behavior, not only internal Python calls.
- Preview migrations and identity linking; do not add fuzzy automatic merges.
- Treat multi-file operations and external side effects as recoverable workflows,
  not as automatically atomic transactions.

## Documentation changes

Start with the README, then architecture, then the guide that owns the workflow.
Use [GitHub Markdown guidance](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github)
and the [documentation map](docs/README.md). Check relative files and heading anchors.

Separate executable commands from example output and file contents. Validate documented
flags against current source. Do not use a static test-count badge as a substitute for
current CI results.

Do not restyle historical issues, planning documents, client prompts or vault templates
as a side effect of editing user guides.

## Current priority

[Automatic continuity #61](https://github.com/vib28/ai-memory-hub/issues/61) is the first
runtime priority. Keep its capture/session dependency chain coordinated. The
[paired token benchmark](docs/session-handoff-benchmark.md) is required acceptance,
not an optional marketing measurement.
