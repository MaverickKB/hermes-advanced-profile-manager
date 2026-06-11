from __future__ import annotations

import sys

sys.path.insert(0, "webui")

import capabilities


def test_no_agent_source_reports_unknown(iso):
    caps = capabilities.agent_capabilities(refresh=True)
    assert caps["agent_repo"] is None
    for key in ("profile_delegation", "channel_profiles", "skill_groups"):
        assert caps["extensions"][key]["runtime_support"] == "unknown"


def test_detects_implemented_and_missing_extensions(iso):
    repo = iso["home"] / "hermes-agent"
    repo.mkdir()
    (repo / "model_tools.py").write_text("TOOL_TO_TOOLSET_MAP = {}\n", encoding="utf-8")
    (repo / "router.py").write_text(
        "def route(cfg):\n    return cfg.get('channel_profiles')\n", encoding="utf-8")
    caps = capabilities.agent_capabilities(refresh=True)
    assert caps["agent_repo"] == str(repo)
    assert caps["extensions"]["channel_profiles"]["runtime_support"] == "implemented"
    assert caps["extensions"]["profile_delegation"]["runtime_support"] == "not-implemented"
    assert caps["extensions"]["skill_groups"]["runtime_support"] == "not-implemented"


def test_capability_cache_invalidates_on_change(iso):
    repo = iso["home"] / "hermes-agent"
    repo.mkdir()
    (repo / "model_tools.py").write_text("x = 1\n", encoding="utf-8")
    caps = capabilities.agent_capabilities(refresh=True)
    assert caps["extensions"]["profile_delegation"]["runtime_support"] == "not-implemented"
    # cached result reused
    again = capabilities.agent_capabilities()
    assert again == caps
    # implementing the surface changes the fingerprint source file
    import time
    time.sleep(0.02)
    (repo / "model_tools.py").write_text("def delegate_profile():\n    profile_delegation = {}\n", encoding="utf-8")
    fresh = capabilities.agent_capabilities(refresh=True)
    assert fresh["extensions"]["profile_delegation"]["runtime_support"] == "implemented"
