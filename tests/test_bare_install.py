"""Clean-install experience: upstream hermes-agent keeps the default profile
at the installation root (~/.hermes/config.yaml, SOUL.md, .env, auth.json) and
creates profiles/ only when named profiles exist. The manager must recognize
that layout."""
from __future__ import annotations

import sys

sys.path.insert(0, "webui")

import hermes_paths
import server


def _bare_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text(
        "model:\n  provider: nous\n  default: Hermes-4-405B\ntoolsets:\n  - file\n",
        encoding="utf-8",
    )
    (home / "SOUL.md").write_text("# default soul\n", encoding="utf-8")
    (home / ".env").write_text("EXAMPLE=1\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("PROFILE_MANAGER_HERMES_HOME", raising=False)
    return home


def test_bare_home_resolves_without_profiles_dir(tmp_path, monkeypatch):
    home = _bare_home(tmp_path, monkeypatch)
    assert hermes_paths.hermes_home() == home


def test_default_profile_maps_to_home_root(tmp_path, monkeypatch):
    home = _bare_home(tmp_path, monkeypatch)
    assert hermes_paths.profile_dir("default") == home
    assert hermes_paths.config_path("default") == home / "config.yaml"
    assert hermes_paths.load_profile_config("default")["model"]["provider"] == "nous"


def test_bare_install_lists_default_profile(tmp_path, monkeypatch):
    _bare_home(tmp_path, monkeypatch)
    assert hermes_paths.list_profile_names() == ["default"]
    profiles = server.profile_list()
    assert [p["name"] for p in profiles] == ["default"]
    assert profiles[0]["has_config"] is True
    assert server.state_default_profile() == "default"


def test_named_profiles_coexist_with_root_default(tmp_path, monkeypatch):
    home = _bare_home(tmp_path, monkeypatch)
    coder = home / "profiles" / "coder"
    coder.mkdir(parents=True)
    (coder / "config.yaml").write_text("model:\n  provider: nous\n  default: Hermes-4-405B\n", encoding="utf-8")
    names = hermes_paths.list_profile_names()
    assert names[0] == "default"
    assert "coder" in names
    assert hermes_paths.profile_dir("coder") == coder
    # a real profiles/default directory wins over the root mapping
    explicit = home / "profiles" / "default"
    explicit.mkdir()
    assert hermes_paths.profile_dir("default") == explicit
