from __future__ import annotations

import sys

sys.path.insert(0, "webui")

import pytest

import identity_files
from conftest import audit_events
from hermes_paths import load_profile_config


def test_identity_status_provenance(iso):
    status = identity_files.identity_status("alpha")
    by_name = {f["name"]: f for f in status["files"]}
    assert by_name["SOUL.md"]["status"] == "profile-local"
    assert by_name["HERMES.md"]["status"] == "inherited-from-default"
    assert by_name["AGENTS.md"]["status"] == "missing"
    assert status["system_prompt"]["present"] is True
    assert status["system_prompt"]["text"] == "You are alpha."


def test_write_identity_requires_confirm(iso):
    with pytest.raises(ValueError):
        identity_files.write_identity_file("alpha", "SOUL.md", "# new", confirm=False)


def test_write_identity_backs_up_and_audits(iso):
    result = identity_files.write_identity_file("alpha", "SOUL.md", "# replaced\n", confirm=True)
    assert result["ok"] and result["backup"]
    assert (iso["alpha"] / "SOUL.md").read_text() == "# replaced\n"
    assert any(e["event"] == "write_identity_file" for e in audit_events())


def test_copy_identity_from_default(iso):
    result = identity_files.copy_identity_file("alpha", "HERMES.md", "default", confirm=True)
    assert result["entry"]["status"] == "profile-local"
    assert (iso["alpha"] / "HERMES.md").read_text() == "# default hermes\n"


def test_copy_identity_from_profile(iso):
    identity_files.copy_identity_file("beta", "SOUL.md", "alpha", confirm=True)
    assert (iso["beta"] / "SOUL.md").read_text() == "# alpha soul\n"


def test_rejects_non_identity_file(iso):
    with pytest.raises(ValueError):
        identity_files.write_identity_file("alpha", "config.yaml", "x", confirm=True)


def test_set_system_prompt(iso):
    result = identity_files.set_system_prompt("alpha", "New prompt.", confirm=True)
    assert result["ok"] and result["backup"]
    cfg = load_profile_config("alpha")
    assert cfg["agent"]["system_prompt"] == "New prompt."
