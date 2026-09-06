# Documentation

Start with [AI Memory Hub](../README.md) for what the project does and what is still planned.

## Install and operate

| Guide | Purpose |
| --- | --- |
| [Installation](INSTALLATION.md) | Set up the environment and vault |
| [Client connections](CLIENTS.md) | Connect an AI tool and verify its configuration |
| [Configuration](CONFIGURATION.md) | Environment variables, write modes and optional models |
| [Usage](USAGE.md) | Review, search, sessions, imports, identity and undo |
| [Troubleshooting](TROUBLESHOOTING.md) | Diagnose common failures without losing data |
| [FAQ](FAQ.md) | Short answers to common questions |

## Understand and contribute

- [Architecture](../ARCHITECTURE.md): module map, storage and boundaries.
- [Contributing](../CONTRIBUTING.md): development checks and issue workflow.
- [Quick start](../QUICK_START.md): short Windows entry point.
- [Setup guide](../INSTALLATION_GUIDE.md): guided route through the installation references.

## Plans and historical records

These retain their existing structured tracking format:

- [Implementation roadmap](local-memory-plan.md).
- [Automatic session continuity](automatic-session-continuity.md).
- [Two-tool handoff benchmark](session-handoff-benchmark.md).
- [Vault documentation standards](vault-documentation-standards.md).

[FIXLOG](../FIXLOG.md) and [release notes](../RELEASE_NOTES_v0.2.md) record historical work.

## Writing conventions

User guides use descriptive headings, relative repository links, language-tagged code
blocks and alerts for meaningful cautions. Commands and expected output stay separate.
Use a table for repeated comparisons, not as a replacement for every paragraph.

Follow [GitHub's writing and formatting guidance](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github).
Do not change issue/roadmap templates, client prompts or vault-record formats merely
to restyle a user guide. A formatting pass is not permission to change runtime behavior.
