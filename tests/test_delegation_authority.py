from __future__ import annotations

import sys

sys.path.insert(0, "webui")

import pytest

import delegation_authority as da
from hermes_paths import config_path, dump_yaml, load_profile_config


def _set_pd(profile, block):
    cfg = load_profile_config(profile)
    cfg["profile_delegation"] = block
    config_path(profile).write_text(dump_yaml(cfg), encoding="utf-8")


def test_view_classifies_targets(iso):
    _set_pd("alpha", {"allowed_profiles": ["beta", "be_ta", "ghost", "default"], "allow_self": True, "max_depth": 2})
    view = da.delegation_view("alpha")
    by_name = {t["name"]: t for t in view["allowed_profiles"]}
    assert by_name["beta"]["status"] == "ok"
    assert by_name["default"]["status"] == "ok"  # built-in home profile
    assert by_name["be_ta"]["status"] == "stale-name" and by_name["be_ta"]["resolves_to"] == "beta"
    assert by_name["ghost"]["status"] == "missing"
    assert view["stale_count"] == 1 and view["missing_count"] == 1
    assert view["allow_self"] is True and view["max_depth"] == 2


def test_view_reports_toolset_gates_and_worker_route(iso):
    view = da.delegation_view("alpha")
    # alpha config has neither delegation toolset enabled
    assert view["gates"]["profile_delegation_toolset"] == "not enabled"
    assert view["worker_route"]["provider"] == "nous-api"
    assert view["worker_route"]["orchestrator_enabled"] is False


def test_inbound_authority_detection(iso):
    _set_pd("beta", {"allowed_profiles": ["alpha"]})
    view = da.delegation_view("alpha")
    assert view["inbound"] == [{"profile": "beta", "declared_as": "alpha", "exact": True}]
    # stale inbound name still resolves
    _set_pd("beta", {"allowed_profiles": ["al_pha"]})
    view = da.delegation_view("alpha")
    assert view["inbound"][0]["exact"] is False


def test_set_authority_writes_with_backup(iso):
    result = da.set_delegation_authority("alpha", {
        "allowed_profiles": ["beta", "default"],
        "allow_self": False,
        "max_depth": 1,
    }, confirm=True)
    assert result["ok"] and result["backup"]
    cfg = load_profile_config("alpha")
    assert cfg["profile_delegation"]["allowed_profiles"] == ["beta", "default"]
    assert cfg["profile_delegation"]["max_depth"] == 1


def test_set_authority_rejects_missing_targets(iso):
    with pytest.raises(ValueError, match="ghost"):
        da.set_delegation_authority("alpha", {"allowed_profiles": ["ghost"]}, confirm=True)


def test_set_authority_requires_confirm(iso):
    with pytest.raises(ValueError):
        da.set_delegation_authority("alpha", {"allowed_profiles": []}, confirm=False)


def test_fix_stale_targets(iso):
    _set_pd("alpha", {"allowed_profiles": ["be_ta", "beta", "default"]})
    result = da.fix_stale_targets("alpha", confirm=True)
    assert result["fixed"] == [{"from": "be_ta", "to": "beta"}]
    cfg = load_profile_config("alpha")
    # de-duplicated: be_ta resolved into existing beta
    assert cfg["profile_delegation"]["allowed_profiles"] == ["beta", "default"]


def test_fix_stale_noop_when_clean(iso):
    _set_pd("alpha", {"allowed_profiles": ["beta"]})
    result = da.fix_stale_targets("alpha", confirm=True)
    assert result["fixed"] == [] and "backup" not in result
