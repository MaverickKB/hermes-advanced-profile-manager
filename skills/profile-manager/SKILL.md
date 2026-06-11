---
name: profile-manager
description: Launch, check, or stop the Hermes Advanced Profile Manager WebUI — a full-power visual configuration surface for Hermes profiles, skills, skill groups, delegation authority, MCP servers, providers, and backups. Use when the user asks to open/launch/start the profile manager, inspect or configure profiles visually, explore the profile system graph, or shut the manager down.
---

# Hermes Advanced Profile Manager

A local WebUI for full-power Hermes profile management: readiness verdicts,
identity files, skills and skill groups, toolsets, MCP servers, providers and
model routes, auth/env (masked), live delegation authority, team planning,
backups/rollback/audit, and an interactive Explorer graph of every profile.

## Launch (background — does not occupy a terminal)

```bash
scripts/launch-profile-manager start
```

Prints the URL (default `http://127.0.0.1:5194/`) and returns immediately.
Safe to repeat: if already running it just reports the URL.

## Other commands

```bash
scripts/launch-profile-manager status    # running? where?
scripts/launch-profile-manager stop      # shut down (also: ⏻ button in the UI)
scripts/launch-profile-manager open      # open the UI in a browser
scripts/launch-profile-manager run       # foreground mode (debugging)
```

Options for any command: `--port <n>`, `--host <addr>`,
`--hermes-home <path>` (profile-scoped sessions should pass the real
installation root), `--no-open`.

## Notes for agents

- The server binds localhost only and writes nothing without an explicit
  confirmed action; every write takes a backup first and is audited.
- After config changes, suggest the Overview tab's readiness check (or
  `GET /api/profiles/<name>/readiness?live=1`) as verification evidence.
- If the checkout cannot be located, set `PROFILE_MANAGER_HOME` or re-run
  `scripts/profile-manager install-skill` from the checkout.
