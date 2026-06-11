from __future__ import annotations

import json
import sys

sys.path.insert(0, "webui")

import pytest

import env_auth
from conftest import audit_events


def test_env_status_masks_values(iso):
    status = env_auth.env_status("alpha")
    assert status["scope"] == "profile-specific"
    blob = json.dumps(status)
    assert "alphasecret123" not in blob
    keys = {k["key"] for k in status["keys"]}
    assert keys == {"ALPHA_TOKEN", "SHARED"}
    assert "GLOBAL_KEY" in status["global_keys"]


def test_env_apply_set_and_remove(iso):
    result = env_auth.env_apply("alpha", [
        {"op": "set", "key": "NEW_KEY", "value": "v1"},
        {"op": "remove", "key": "SHARED"},
    ], confirm=True)
    assert result["ok"] and result["backup"]
    keys = {k["key"] for k in result["status"]["keys"]}
    assert keys == {"ALPHA_TOKEN", "NEW_KEY"}
    # audit must contain key names only, never values
    blob = json.dumps(audit_events())
    assert "NEW_KEY" in blob and "v1" not in blob


def test_env_apply_requires_confirm(iso):
    with pytest.raises(ValueError):
        env_auth.env_apply("alpha", [{"op": "set", "key": "A", "value": "b"}], confirm=False)


def test_env_copy_from_global(iso):
    result = env_auth.env_copy("beta", "global", confirm=True)
    keys = {k["key"] for k in result["status"]["keys"]}
    assert keys == {"GLOBAL_KEY", "SHARED"}


def test_env_reveal_single_value_and_audit(iso):
    revealed = env_auth.env_reveal("alpha", "ALPHA_TOKEN")
    assert revealed["value"] == "alphasecret123"
    events = [e for e in audit_events() if e["event"] == "env_reveal"]
    assert events and events[-1]["details"]["key"] == "ALPHA_TOKEN"
    assert "alphasecret123" not in json.dumps(events)


def test_env_file_mode_is_private(iso):
    env_auth.env_apply("alpha", [{"op": "set", "key": "X", "value": "y"}], confirm=True)
    assert (iso["alpha"] / ".env").stat().st_mode & 0o777 == 0o600


def test_auth_status_redacted_and_stale(iso):
    status = env_auth.auth_status("alpha")
    assert status["source"] == "profile-local"
    assert status["stale"] is True  # 2025 updated_at
    blob = json.dumps(status)
    assert "SECRET-ALPHA" not in blob
    assert "stale-one" in status["metadata"]["providers"]


def test_auth_status_inherited(iso):
    status = env_auth.auth_status("beta")
    assert status["source"] == "inherited-from-default"
    assert "SECRET-DEFAULT" not in json.dumps(status)


def test_auth_copy_from_default(iso):
    result = env_auth.auth_copy("beta", "default", confirm=True)
    assert result["status"]["source"] == "profile-local"


def test_auth_remove_provider(iso):
    result = env_auth.auth_remove_provider("alpha", "stale-one", confirm=True)
    assert "stale-one" not in result["status"]["metadata"]["providers"]
    assert "stale-one" not in result["status"]["metadata"]["credential_pool"]


def test_auth_use_default_removes_local(iso):
    result = env_auth.auth_use_default("alpha", confirm=True)
    assert result["status"]["source"] == "inherited-from-default"
    assert result["backup"]


def test_required_env_findings(iso):
    from hermes_paths import load_profile_config
    cfg = load_profile_config("alpha")
    findings = env_auth.required_env_findings("alpha", cfg)
    # NOUS_API_KEY declared by provider but absent everywhere
    assert any("NOUS_API_KEY" in f["message"] for f in findings)
    # ALPHA_TOKEN present in profile .env, so no warning about it
    assert not any("ALPHA_TOKEN" in f["message"] and f["severity"] == "warning" for f in findings)
