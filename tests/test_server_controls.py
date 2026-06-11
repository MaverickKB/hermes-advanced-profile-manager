from __future__ import annotations

import sys

sys.path.insert(0, "webui")

import pytest

import server
from hermes_paths import load_profile_config


def test_apply_change_set_bounded(iso):
    cs = {
        "workflow": "test",
        "skill_assignments": [{"profile": "alpha", "selected": ["skill-one", "not-installed"]}],
        "config_patches": [
            {"op": "merge", "path": "/model", "value": {"provider": "nous-api", "default": "Hermes-4-405B"}},
            {"op": "merge", "path": "/unsupported", "value": {}},
        ],
        "prompt_changes": [{"profile": "alpha"}],
    }
    result = server.apply_change_set("alpha", cs, confirm=True)
    assert result["ok"] and result["backup"]
    applied_sections = {a["section"] for a in result["applied"]}
    assert {"skill_assignments", "config_patches"} <= applied_sections
    skipped_sections = {s["section"] for s in result["skipped"]}
    assert {"config_patches", "prompt_changes", "skill_assignments"} <= skipped_sections
    cfg = load_profile_config("alpha")
    assert cfg["model"]["provider"] == "nous-api"


def test_apply_change_set_requires_confirm(iso):
    with pytest.raises(ValueError):
        server.apply_change_set("alpha", {}, confirm=False)


def test_create_backup_compare_and_rollback_last_apply(iso):
    # apply a config change through the bounded changeset path (creates backup + audit)
    server.apply_change_set("alpha", {
        "workflow": "test",
        "config_patches": [{"op": "merge", "path": "/toolsets", "value": ["web"]}],
    }, confirm=True)
    cfg = load_profile_config("alpha")
    assert cfg["toolsets"] == ["web"]

    from hermes_paths import list_backups
    backups = list_backups("alpha")
    assert backups
    cmp_result = server.compare_backup("alpha", backups[0]["name"])
    assert cmp_result["changed"] is True
    assert "toolsets" in cmp_result["diff"]

    rb = server.rollback_last_apply("alpha")
    assert rb["ok"]
    cfg = load_profile_config("alpha")
    assert cfg["toolsets"] == ["web", "file", "terminal"]


def test_rollback_last_apply_without_history(iso):
    with pytest.raises(ValueError):
        server.rollback_last_apply("beta")


def test_export_profile_package_excludes_secrets(iso):
    package = server.export_profile_package("alpha")
    import json
    blob = json.dumps(package)
    assert "alphasecret123" not in blob
    assert "SECRET-ALPHA" not in blob
    assert "SOUL.md" in package["identity_files"]
    assert package["config_yaml"]


def test_raw_files_view_masks_env_and_auth(iso):
    view = server.raw_files_view("alpha")
    import json
    blob = json.dumps(view)
    assert "alphasecret123" not in blob
    assert "SECRET-ALPHA" not in blob
    assert view["config"]["exists"] is True
    names = {f["name"] for f in view["identity"]}
    assert names == {"SOUL.md", "HERMES.md", "AGENTS.md"}


def test_team_plan_pair(iso):
    plan = server.team_plan({
        "primary": "alpha",
        "mode": "pair",
        "specialists": [{"name": "beta", "role": "worker", "max_risk": "read-only", "domains": ["rmm-support"]}],
    })
    assert plan["mode"] == "pair"
    assert plan["topology"]["specialists"] == ["beta"]
    assert plan["change_set"]["team_relationship_changes"]


def test_skill_catalog_why_selected(iso):
    import skill_groups
    skill_groups.upsert_group("why-group", {"required_skills": ["skill-one"]})
    catalog = server.scan_skill_catalog("alpha")
    one = next(s for s in catalog["skills"] if s["name"] == "skill-one")
    assert any(w.startswith("group-required") for w in one["why_selected"])
    assert any(w.startswith("direct") for w in one["why_selected"])
