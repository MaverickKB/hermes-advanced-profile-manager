from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "webui")

import hermes_paths  # noqa: E402


ALPHA_CONFIG = """\
model:
  provider: nous
  default: hermes-4.1
providers:
  nous-api:
    base_url: https://inference-api.nousresearch.com/v1
    api_mode: chat_completions
    default_model: Hermes-4-405B
    key_env: NOUS_API_KEY
fallback_providers:
  - provider: nous-api
    model: Hermes-4-405B
    base_url: https://inference-api.nousresearch.com/v1
delegation:
  provider: nous-api
  model: Hermes-4-405B
  orchestrator_enabled: false
auxiliary:
  vision:
    provider: nous
    model: hermes-4.1
toolsets:
  - web
  - file
  - terminal
agent:
  disabled_toolsets:
    - browser
    - homeassistant
  system_prompt: "You are alpha."
mcp_servers:
  alpha-mcp:
    command: /usr/bin/true
    args: ["mcp"]
    enabled: true
    env:
      ALPHA_TOKEN: "${ALPHA_TOKEN}"
skills: {}
"""


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """Isolated Hermes home + manager state for control-surface tests."""
    home = tmp_path / "hermes"
    profiles = home / "profiles"
    profiles.mkdir(parents=True)
    (home / "SOUL.md").write_text("# default soul\n", encoding="utf-8")
    (home / "HERMES.md").write_text("# default hermes\n", encoding="utf-8")
    (home / ".env").write_text("GLOBAL_KEY=globalvalue\nSHARED=one\n", encoding="utf-8")
    (home / "auth.json").write_text(json.dumps({
        "active_provider": "nous",
        "providers": {"nous": {"token": "SECRET-DEFAULT"}},
        "credential_pool": {"nous": {}, "openai-codex": {}},
        "updated_at": "2026-06-01T00:00:00+00:00",
        "version": 3,
    }), encoding="utf-8")

    alpha = profiles / "alpha"
    alpha.mkdir()
    (alpha / "config.yaml").write_text(ALPHA_CONFIG, encoding="utf-8")
    (alpha / "SOUL.md").write_text("# alpha soul\n", encoding="utf-8")
    (alpha / ".env").write_text("ALPHA_TOKEN=alphasecret123\nSHARED=two\n", encoding="utf-8")
    (alpha / "auth.json").write_text(json.dumps({
        "active_provider": "nous",
        "providers": {"nous": {"token": "SECRET-ALPHA"}, "stale-one": {"token": "OLD"}},
        "credential_pool": {"nous": {}, "stale-one": {}},
        "updated_at": "2025-01-01T00:00:00+00:00",
        "version": 3,
    }), encoding="utf-8")
    skills = alpha / "skills"
    for skill in ("skill-one", "skill-two", "skill-three"):
        d = skills / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: test skill {skill}\n---\nBody.\n", encoding="utf-8")

    beta = profiles / "beta"
    beta.mkdir()
    (beta / "config.yaml").write_text("model:\n  provider: ''\n  default: ''\ntoolsets: []\n", encoding="utf-8")

    state = tmp_path / "manager-state"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(hermes_paths, "STATE", state)
    monkeypatch.setattr(hermes_paths, "BACKUPS", state / "backups")
    monkeypatch.setattr(hermes_paths, "AUDIT", state / "audit.jsonl")
    monkeypatch.setattr(hermes_paths, "LIBRARY", state / "library")
    return {"home": home, "profiles": profiles, "state": state, "alpha": alpha, "beta": beta}


def audit_events() -> list[dict]:
    if not hermes_paths.AUDIT.exists():
        return []
    return [json.loads(line) for line in hermes_paths.AUDIT.read_text().splitlines() if line.strip()]
