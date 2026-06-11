from __future__ import annotations

import sys

sys.path.insert(0, "webui")

import pytest

from readiness import readiness_report
from team_topology import build_team_graph
from delegation_graph import ProfileNode


def test_readiness_missing_config(iso):
    report = readiness_report("nonexistent-profile", live=False)
    assert report["verdict"] == "not-ready"
    assert report["blockers"]


def test_readiness_offline_report_shape(iso):
    report = readiness_report("alpha", live=False)
    assert report["verdict"] in {"ready", "ready-with-warnings"}
    labels = {e["label"] for e in report["evidence"]}
    assert {"primary route", "auth", "env scope", "secrets", "identity", "worker route", "duplicates"} <= labels
    # secrets are referenced via ${}, no inline secret warning expected
    secrets_evidence = next(e for e in report["evidence"] if e["label"] == "secrets")
    assert secrets_evidence["ok"] is True


def test_readiness_flags_missing_env_key(iso):
    report = readiness_report("alpha", live=False)
    assert any("NOUS_API_KEY" in w for w in report["warnings"])


def _primary_node(name="alpha"):
    return ProfileNode(
        name=name, role="orchestrator", domains=["profile-management"],
        allowed_hosts=["local"], max_risk="coordination",
        required_skills=[], required_toolsets=[], protected_domains=[],
    )


def test_pair_topology(iso):
    graph, findings = build_team_graph("alpha", _primary_node(), "pair", [
        {"name": "beta", "role": "worker", "max_risk": "read-only", "domains": ["rmm-support"]},
    ])
    assert set(graph.nodes) == {"alpha", "beta"}
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.max_risk == "read-only"
    assert "continuity" in edge.context_exclude
    assert not any(f.severity == "warning" for f in findings)


def test_pair_topology_wrong_count_warns(iso):
    _, findings = build_team_graph("alpha", _primary_node(), "pair", [])
    assert any("expects 1 specialist" in f.message for f in findings)


def test_missing_specialist_requires_provisioning_choice(iso):
    _, findings = build_team_graph("alpha", _primary_node(), "team", [
        {"name": "ghost-profile"},
    ])
    assert any("no provisioning choice" in f.message for f in findings)


def test_future_dependency_finding(iso):
    graph, findings = build_team_graph("alpha", _primary_node(), "team", [
        {"name": "future-one", "provisioning": "future-dependency"},
    ])
    assert "future-one" in graph.nodes
    assert any("future dependency" in f.message for f in findings)


def test_orchestrator_mode_wants_evaluator(iso):
    _, findings = build_team_graph("alpha", _primary_node(), "orchestrator", [
        {"name": "beta", "role": "specialist"},
    ])
    assert any("evaluator/critic" in f.message for f in findings)


def test_orchestrator_mode_with_evaluator(iso):
    graph, findings = build_team_graph(
        "alpha", _primary_node(), "orchestrator",
        [{"name": "beta", "role": "specialist"}],
        evaluator={"name": "critic", "provisioning": "future-dependency"},
    )
    assert graph.nodes["critic"].role == "reviewer"
    assert graph.nodes["critic"].max_risk == "read-only"
    assert not any("evaluator/critic" in f.message for f in findings)


def test_invalid_mode_rejected(iso):
    with pytest.raises(ValueError):
        build_team_graph("alpha", _primary_node(), "swarm", [])
