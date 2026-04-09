# Skitter Repository Notes

This file is for contributors and coding agents working on the Skitter codebase.

## Most Important Rule

If you change Python code, run the full test suite afterwards:

```bash
./venv/bin/python -m pytest -q
```

Targeted tests are fine while iterating, but finish with the full `pytest` run after every Python change.

## Project Layout

- `skitter/`: Python API server, runtime, transports, tools, scheduler, memory
- `admin-web/`: React admin UI
- `skitter-tui/`: terminal client
- `skitter-menubar/`: macOS menu bar app
- `skitter-ios/`: iPhone/iPad client
- `docs/`: MkDocs documentation
- `workspace-skeleton/`: files copied into newly created profile workspaces

## Workspace / Profiles

- Agent profiles are first-class and profile-scoped.
- Profile workspaces live at:

```text
workspace/users/<user_id>/<profile_slug>/
```

- Do not reintroduce old “main workspace plus nested profiles” assumptions.
- New profile workspaces are created from `workspace-skeleton`.
- Existing workspaces must not be silently backfilled on later runs.

## Testing / Validation

- Python changes: run `./venv/bin/python -m pytest -q`
- Admin web changes: run `cd admin-web && npm run build`
- Docs changes: keep `mkdocs.yml` in sync with added or moved pages

If a test fails because of stale import/module collisions in tests, remember that:

- `skitter/tests/`
- `skitter/tests/unit/`
- `skitter/tests/e2e/`

are Python packages on purpose, to avoid duplicate test-module basename issues.

## Implementation Notes

- Prefer `rg` / `rg --files` for search.
- Use `apply_patch` for manual file edits.
- Keep changes small and reuse existing services/helpers instead of adding parallel code paths.
- Multi-agent support is profile-based:
  - sessions, memory, secrets, schedules, jobs, heartbeats, and transport routing are profile-aware
  - Discord supports one shared default bot from `config.yaml` plus dedicated per-profile overrides
- Heartbeats are per profile, not per user.
- The reserved silent-response token is `SKITTER_NO_REPLY`.

## Config Notes

- Docker is the default deployment path.
- `workspace.root` defaults to `/workspace` in Docker setups.
- The shared default Discord bot token still comes from `config.yaml`.
- Dedicated per-profile Discord bot tokens are managed separately through transport accounts.

## When Touching Prompt / Agent Behavior

- Check both repo docs and `workspace-skeleton/AGENTS.md`.
- Keep command syntax and docs aligned.
- If you change `/profile` behavior, update:
  - `docs/api/commands.md`
  - relevant API / e2e tests

## Keep It Clean

- Do not commit secrets, tokens, or machine-local paths unless they are already intended config examples.
- Do not remove useful diagnostics lightly; they help a lot with Discord and transport debugging.
