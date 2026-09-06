# Setup guide

Follow this route from a fresh checkout to a verified memory connection. Detailed
instructions have one home in docs/ so setup steps do not drift between copies.

## 1. Prepare the environment

Read [installation prerequisites and source setup](docs/INSTALLATION.md).
Choose a dedicated vault folder and the branch you intend to use.

## 2. Initialize the vault

Follow [environment and vault setup](docs/INSTALLATION.md#create-the-environment-and-vault).
Existing vault files are preserved; initialization is not an instruction-template upgrade.

## 3. Connect your client

Use [client connections](docs/CLIENTS.md). Confirm the actual vault and write mode,
especially when a registration already exists. Optional ChatGPT tunnel setup is separate.

## 4. Verify review behavior

Open the [dashboard](docs/INSTALLATION.md#open-the-dashboard), check memory_policy in
the client, and verify a test proposal before approving it.

## 5. Configure optional components

Read [configuration](docs/CONFIGURATION.md) for language models, embeddings and Git history.
Review [backup guidance](docs/USAGE.md#undo-and-backup) before treating any database as disposable.

## 6. Maintain and troubleshoot

- [Everyday usage](docs/USAGE.md).
- [Troubleshooting](docs/TROUBLESHOOTING.md).
- [Development checks](CONTRIBUTING.md).
- [Architecture and boundaries](ARCHITECTURE.md).

> [!NOTE]
> Automatic token/time checkpoints, startup handoff and GitHub session publishing are
> not available yet. Their [plan](docs/automatic-session-continuity.md) and
> [required benchmark](docs/session-handoff-benchmark.md) are separate from setup.
