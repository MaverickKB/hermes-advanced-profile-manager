# Hermes Advanced Profile Manager

A local, dependency-light WebUI for **full-power management of
[Hermes Agent](https://github.com/NousResearch/hermes-agent) profiles** —
the visual operating surface for everything a profile really is: identity,
instructions, auth, env, skills, skill groups, toolsets, MCP servers,
providers, delegation authority, team topology, backups, and audit.

Built for two audiences at once: **beginners** get readiness verdicts,
guided flows, and one-click safety (every write confirms, backs up, and
audits); **power users** get the complete config surface, live route/MCP
tests, a system-wide interactive graph, and raw-file editing — without ever
being reduced to a read-only dashboard.

## Quickstart

Requirements: Python 3.10+ on macOS or Linux (Windows works for most flows).

```bash
git clone https://github.com/MaverickKB/hermes-advanced-profile-manager.git
cd hermes-advanced-profile-manager
./scripts/profile-manager start
```

That's it. The first run creates a virtualenv, installs PyYAML, starts the
server **in the background** (no terminal occupied), opens
`http://127.0.0.1:5194/`, and prints how to stop it.

```bash
./scripts/profile-manager status     # running? where?
./scripts/profile-manager stop      # shut down (or use the ⏻ button in the UI)
./scripts/profile-manager run       # foreground mode for debugging
./scripts/profile-manager start --port 6001 --hermes-home ~/.hermes
```

## Launch from a Hermes agent

```bash
./scripts/profile-manager install-skill
```

installs an agent-launchable skill into your Hermes home, pinned to this
checkout. Agents can then start/stop/check the manager themselves
(`scripts/launch-profile-manager start|stop|status`).

## What you get

1. **Overview** — an evidence-backed readiness verdict: *can this profile
   safely operate right now?* (live route tests, MCP handshakes with tool
   counts, auth/env state, secret hygiene — never config presence alone)
2. **Purpose & intent** — build profiles from the job, not YAML
3. **Identity & instructions** — SOUL.md / HERMES.md / AGENTS.md with
   provenance, plus the system prompt
4. **Domains & roles** — live library with inline creation
5. **Skill groups** — Hermes-native capability manifests
   (`~/.hermes/skill_groups/*.yaml`, `skill_groups.enabled[]` config refs)
6. **Skills selector** — dual-list assignment with why-selected provenance
7. **Toolsets & tools** — real registry inspection with per-tool risk
8. **MCP servers** — provenance, live handshake tests, discovered tool
   surfaces with risk classification
9. **Providers & routes** — usage maps, auth/completion tests, safe route
   replacement
10. **Auth & secrets** — auth source policy and a masked `.env` editor
    (values never displayed except a single audited reveal)
11. **Delegation & team** — the *live* delegation authority list with
    grant/revoke, stale-name fixes, and gate status, plus a draft team planner
12. **ChangeSet** — generated plans with bounded, reported apply
13. **Validate & dry-run** — schema/secret checks, diff, live smoke
14. **Backups & audit** — backup now, compare, restore, rollback-last-apply,
    secret-free export
15. **Raw files** — the power editor, last (where it belongs)
16. **✦ Explorer** — an interactive graph of your whole installation
    (constellation / mind map / flow views) that surfaces broken delegation
    targets, stale aliases, and orphaned profiles at a glance

## Native vs. extension surfaces — honest labeling

Most of what this manager edits is **upstream-native Hermes config**: model
routes, providers/fallbacks/auxiliary, MCP servers, toolsets,
`agent.disabled_toolsets`, `skills.disabled`, the system prompt, identity
files, auth/env.

Three surfaces are **extensions** — designed in hermes-agent's own planning
docs or pioneered in forks, but not yet implemented by the official runtime:

- `profile_delegation.allowed_profiles` (delegation authority)
- `discord.channel_profiles` (channel → profile routing)
- `skill_groups.enabled[]` + `~/.hermes/skill_groups/*.yaml` manifests

The manager detects at runtime whether *your* installed hermes-agent
implements each surface (by scanning its source) and labels the relevant
tabs: **native support** when implemented, or **extension — config is
forward-compatible but inert on this runtime** when not. Writing these keys
is always safe (official Hermes ignores unknown config), and this tool is
intended as the working reference for upstreaming them.

## Safety model

- Binds `127.0.0.1` only.
- Every write requires an explicit confirm, takes a backup first, and appends
  an audit record (key names only — never secret values).
- Exports exclude `.env` and `auth.json` by design.
- No system-specific paths in the runtime: the Hermes home resolves via
  `PROFILE_MANAGER_HERMES_HOME` → `HERMES_HOME` (with profile-scoped
  ancestor walk) → `~/.hermes`.

## Development

```bash
./scripts/profile-manager run        # foreground server
.venv/bin/pip install pytest
.venv/bin/python -m pytest           # test suite
```

Agent contributors using the
[AetherMind Hermes plugin](https://github.com/MaverickKB/aethermind-hermes-plugin)
get a curated head start: the repo ships a clean `.aethermind/` continuity
seed (mission, architecture, invariants, safety model) to reorient from.

## License

MIT — see `LICENSE`.
