from __future__ import annotations

import sys

sys.path.insert(0, "webui")

import pytest
import yaml

import skill_groups
from hermes_paths import load_profile_config


def test_groups_persist_as_yaml_manifests_in_hermes_home(iso):
    skill_groups.upsert_group("rmm-support-operator", {
        "description": "RMM support operator group",
        "required_skills": ["skill-one", "skill-two"],
        "recommended_skills": ["skill-three"],
        "required_toolsets": ["web", "terminal"],
        "forbidden_toolsets": ["homeassistant"],
        "mcp_dependencies": ["example-rmm"],
        "risk_level": "high",
    })
    manifest_path = iso["home"] / "skill_groups" / "rmm-support-operator.yaml"
    assert manifest_path.exists(), "manifest must live in HERMES_HOME/skill_groups per Hermes storage model"
    manifest = yaml.safe_load(manifest_path.read_text())
    # nested manifest shape, not the manager-flat shape
    assert manifest["id"] == "rmm-support-operator"
    assert manifest["skills"]["required"] == ["skill-one", "skill-two"]
    assert manifest["toolsets"]["forbidden"] == ["homeassistant"]
    assert manifest["mcp_servers"]["required"] == ["example-rmm"]
    assert manifest["repairs"]["dry_run_required"] is True


def test_versioning_on_update(iso):
    skill_groups.upsert_group("vgroup", {"description": "v1"})
    assert skill_groups.get_group("vgroup")["version"] == 1
    skill_groups.upsert_group("vgroup", {"description": "v2"})
    assert skill_groups.get_group("vgroup")["version"] == 2


def test_list_groups_reads_canonical_dir_fresh(iso):
    # a manifest written by external tooling (e.g. hermes itself) must appear
    gdir = iso["home"] / "skill_groups"
    gdir.mkdir(exist_ok=True)
    (gdir / "external-group.yaml").write_text(yaml.safe_dump({
        "id": "external-group",
        "description": "written by hermes, not the manager",
        "skills": {"required": ["skill-one"]},
    }), encoding="utf-8")
    names = {g["name"] for g in skill_groups.list_groups()}
    assert "external-group" in names
    flat = skill_groups.get_group("external-group")
    assert flat["required_skills"] == ["skill-one"]
    assert flat["source"] == "custom"


def test_risk_levels_follow_manifest_model(iso):
    with pytest.raises(ValueError):
        skill_groups.upsert_group("badrisk", {"risk_level": "local-write"})
    skill_groups.upsert_group("okrisk", {"risk_level": "critical"})
    assert skill_groups.get_group("okrisk")["risk_level"] == "critical"


def test_duplicate_adapt(iso):
    skill_groups.upsert_group("base-group", {"required_skills": ["skill-one"]})
    result = skill_groups.duplicate_group("base-group", "adapted-group")
    assert result["group"]["required_skills"] == ["skill-one"]
    assert "Adapted from base-group" in result["group"]["description"]


def test_export_import_roundtrip(iso):
    skill_groups.upsert_group("exportable", {"required_skills": ["skill-one"]})
    exported = skill_groups.export_group("exportable")
    assert exported["format"] == "hermes-skill-group-manifest/v1"
    assert "manifest_yaml" in exported
    skill_groups.delete_group("exportable")
    skill_groups.import_group(exported["group"])
    assert skill_groups.get_group("exportable")["required_skills"] == ["skill-one"]


def test_starter_templates(iso):
    result = skill_groups.create_from_template("hermes-operator")
    assert result["group"]["name"] == "hermes-operator"
    assert "terminal" in result["group"]["required_toolsets"]
    with pytest.raises(ValueError):
        skill_groups.create_from_template("hermes-operator")  # already exists


def test_enable_group_writes_config_reference(iso):
    skill_groups.upsert_group("wired-group", {"required_skills": ["skill-one"]})
    result = skill_groups.set_group_enabled("alpha", "wired-group", True, confirm=True)
    assert result["ok"] and result["backup"]
    cfg = load_profile_config("alpha")
    assert cfg["skill_groups"]["enabled"] == ["wired-group"]
    assert skill_groups.enabled_groups("alpha") == ["wired-group"]
    skill_groups.set_group_enabled("alpha", "wired-group", False, confirm=True)
    assert skill_groups.enabled_groups("alpha") == []


def test_enable_requires_confirm_and_existing_group(iso):
    with pytest.raises(ValueError):
        skill_groups.set_group_enabled("alpha", "nope", True, confirm=False)
    with pytest.raises(KeyError):
        skill_groups.set_group_enabled("alpha", "no-such-group", True, confirm=True)


def test_group_apply_preview(iso):
    skill_groups.upsert_group("preview-group", {
        "required_skills": ["skill-one", "not-installed-skill"],
        "recommended_skills": ["skill-two"],
        "forbidden_skills": ["skill-three"],
        "required_toolsets": ["web", "browser"],
        "forbidden_toolsets": ["terminal"],
    })
    preview = skill_groups.group_apply_preview(
        "preview-group", "alpha",
        catalog_names={"skill-one", "skill-two", "skill-three"},
        enabled_names={"skill-three"},
        toolsets=["web", "file", "terminal"],
    )
    assert set(preview["skills_to_enable"]) == {"skill-one", "skill-two"}
    assert preview["skills_to_disable"] == ["skill-three"]
    assert preview["missing_required_skills"] == ["not-installed-skill"]
    assert preview["toolsets_to_add"] == ["browser"]
    assert preview["forbidden_toolsets_present"] == ["terminal"]
    assert preview["ready"] is False


def test_profiles_using_group_includes_declared(iso):
    skill_groups.upsert_group("usage-group", {"required_skills": ["skill-one", "skill-two"]})
    skill_groups.set_group_enabled("beta", "usage-group", True, confirm=True)
    usage = skill_groups.profiles_using_group(
        "usage-group",
        {"alpha": {"skill-one", "skill-two"}, "beta": {"skill-one"}, "gamma": set()},
        {"beta": ["usage-group"]},
    )
    by_profile = {u["profile"]: u for u in usage}
    assert by_profile["alpha"]["satisfies"] is True and by_profile["alpha"]["declared"] is False
    assert by_profile["beta"]["declared"] is True and by_profile["beta"]["missing"] == ["skill-two"]
    assert "gamma" not in by_profile


def test_readiness_validates_declared_groups(iso):
    skill_groups.upsert_group("ready-group", {"required_skills": ["skill-one"]})
    skill_groups.set_group_enabled("alpha", "ready-group", True, confirm=True)
    from readiness import readiness_report
    report = readiness_report("alpha", live=False)
    group_evidence = [e for e in report["evidence"] if e["label"] == "group ready-group"]
    assert group_evidence and group_evidence[0]["ok"] is True

    # declaring a group with no manifest must block
    cfg_path = iso["alpha"] / "config.yaml"
    cfg_path.write_text(cfg_path.read_text().replace("- ready-group", "- ghost-group"), encoding="utf-8")
    report = readiness_report("alpha", live=False)
    assert report["verdict"] == "not-ready"
    assert any("ghost-group" in b for b in report["blockers"])


def test_invalid_group_name_rejected(iso):
    with pytest.raises(ValueError):
        skill_groups.upsert_group("Bad Name!", {})


def test_secret_values_never_in_manifest(iso):
    skill_groups.upsert_group("sec-group", {"description": "needs RMM_API_KEY env name only"})
    text = (iso["home"] / "skill_groups" / "sec-group.yaml").read_text()
    assert "alphasecret123" not in text
