from __future__ import annotations

import sys

sys.path.insert(0, "webui")

import system_graph
from hermes_paths import dump_yaml, load_profile_config, config_path


def _scan(profile):
    import server
    return server.scan_skill_catalog(profile)


def _graph(**kw):
    return system_graph.build_system_graph(scan_skills_fn=_scan, **kw)


def _profile_node(graph, name):
    return next(n for n in graph["nodes"] if n["id"] == f"profile:{name}")


def test_graph_nodes_and_edges_shape(iso):
    g = _graph()
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"profile", "provider", "mcp", "skill"} <= kinds
    alpha = _profile_node(g, "alpha")
    assert alpha["skills_enabled"] == 3
    edge_kinds = {e["kind"] for e in g["edges"]}
    assert {"model-route", "mcp", "skill"} <= edge_kinds
    # provider routes carry route kinds
    routes = {e["route"] for e in g["edges"] if e["kind"] == "model-route" and e["source"] == "profile:alpha"}
    assert {"primary", "fallback", "worker-model"} <= routes


def test_broken_delegation_target_detected(iso):
    cfg = load_profile_config("alpha")
    cfg["profile_delegation"] = {"allowed_profiles": ["beta", "ghostprofile", "be_ta"]}
    config_path("alpha").write_text(dump_yaml(cfg), encoding="utf-8")
    g = _graph()
    alpha = _profile_node(g, "alpha")
    assert alpha["health"] == "error"
    blob = " ".join(alpha["health_reasons"])
    assert "ghostprofile" in blob
    # be_ta normalizes to beta -> fuzzy edge with stale-name marker
    fuzzy = [e for e in g["edges"] if e["kind"] == "delegates" and e.get("fuzzy")]
    assert fuzzy and fuzzy[0]["declared_as"] == "be_ta"
    clean = [e for e in g["edges"] if e["kind"] == "delegates" and not e.get("fuzzy")]
    assert any(e["target"] == "profile:beta" for e in clean)


def test_default_is_legitimate_target(iso):
    cfg = load_profile_config("alpha")
    cfg["profile_delegation"] = {"allowed_profiles": ["default"]}
    config_path("alpha").write_text(dump_yaml(cfg), encoding="utf-8")
    g = _graph()
    alpha = _profile_node(g, "alpha")
    assert not any("default" in r for r in alpha["health_reasons"])
    assert any(n["id"] == "profile:default" for n in g["nodes"])


def test_channel_routing_edges(iso):
    cfg = load_profile_config("alpha")
    cfg["discord"] = {"channel_profiles": {"111": "beta", "222": "beta", "333": "alpha"}}
    config_path("alpha").write_text(dump_yaml(cfg), encoding="utf-8")
    g = _graph()
    routes = [e for e in g["edges"] if e["kind"] == "routes"]
    assert len(routes) == 1
    assert routes[0]["target"] == "profile:beta" and routes[0]["channels"] == 2


def test_missing_group_manifest_is_error(iso):
    cfg = load_profile_config("alpha")
    cfg["skill_groups"] = {"enabled": ["nonexistent-group"]}
    config_path("alpha").write_text(dump_yaml(cfg), encoding="utf-8")
    g = _graph()
    alpha = _profile_node(g, "alpha")
    assert alpha["health"] == "error"
    broken = [e for e in g["edges"] if e["kind"] == "group" and e.get("broken")]
    assert broken and broken[0]["target"] == "group:nonexistent-group"


def test_profile_without_config_is_error(iso):
    (iso["profiles"] / "emptyone").mkdir()
    g = _graph()
    empty = _profile_node(g, "emptyone")
    assert empty["health"] == "error"
    assert "no config.yaml" in empty["health_reasons"]


def test_toolset_layer_optional(iso):
    g = _graph(include_toolsets=False)
    assert not any(e["kind"] == "toolset" for e in g["edges"])
    g = _graph(include_toolsets=True)
    toolset_edges = [e for e in g["edges"] if e["kind"] == "toolset" and e["source"] == "profile:alpha"]
    assert {e["target"] for e in toolset_edges} == {"toolset:web", "toolset:file", "toolset:terminal"}


def test_health_counts_consistent(iso):
    g = _graph()
    counts = g["counts"]["health"]
    profiles = [n for n in g["nodes"] if n["kind"] == "profile" and not n.get("builtin")]
    assert counts["ok"] + counts["warn"] + counts["error"] == len(profiles)
