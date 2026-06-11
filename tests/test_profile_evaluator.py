from __future__ import annotations

import sys
sys.path.insert(0, "webui")

from delegation_graph import DelegationEdge, DelegationGraph, ProfileNode
from intent_contracts import IntentContract
from profile_evaluator import evaluate_profile, validate_graph_draft


def _intent() -> IntentContract:
    return IntentContract(
        profile="uxdesigner",
        role="specialist",
        domain="ui-ux",
        mission="Critique visual work and return actionable evidence.",
        tasks=["critique", "prototype"],
        success_criteria=["operator receives screenshot-backed notes"],
        forbidden=["own continuity", "write production profiles"],
        authority_boundary={"max_risk": "local-write", "delegated_domains": ["ui-ux"]},
        evidence_required=["screenshot", "critique notes"],
        confidence=0.9,
        source="explicit",
    )


def _node(**overrides) -> ProfileNode:
    data = {
        "name": "uxdesigner",
        "role": "specialist",
        "domains": ["ui-ux", "visual-design"],
        "allowed_hosts": ["local"],
        "max_risk": "local-write",
        "required_skills": ["claude-design"],
        "required_toolsets": ["browser", "vision", "file"],
        "protected_domains": [],
    }
    data.update(overrides)
    return ProfileNode(**data)


def test_missing_required_skill_yields_missing_finding() -> None:
    result = evaluate_profile(
        profile="uxdesigner",
        intent=_intent(),
        node=_node(required_skills=["claude-design", "design-md"]),
        available_skills=["design-md"],
        available_toolsets=["browser", "vision", "file"],
    )

    assert result["fit_score"] < 100
    assert "skill:claude-design" in result["missing_capabilities"]
    assert any("claude-design" in change for change in result["recommended_changes"])


def test_read_only_profile_with_power_toolsets_warns_over_broad() -> None:
    result = evaluate_profile(
        profile="reviewer",
        intent=IntentContract(
            profile="reviewer",
            role="reviewer",
            domain="code-review",
            mission="Read and review code without writes.",
            tasks=["review"],
            success_criteria=["findings returned"],
            forbidden=["write files"],
            authority_boundary={"max_risk": "read-only", "delegated_domains": []},
            evidence_required=["findings"],
            confidence=0.8,
            source="explicit",
        ),
        node=_node(name="reviewer", role="reviewer", max_risk="read-only", required_toolsets=["terminal", "file", "browser"]),
        available_skills=["claude-design"],
        available_toolsets=["terminal", "file", "browser"],
    )

    assert any("read-only" in item for item in result["over_broad_capabilities"])
    assert result["authority_findings"]


def test_protected_continuity_route_to_specialist_is_blocker() -> None:
    nodes = {
        "default": ProfileNode("default", "orchestrator", ["coordination"], ["local"], "coordination", [], [], ["continuity"]),
        "uxdesigner": _node(),
    }
    edge = DelegationEdge(
        source="default",
        target="uxdesigner",
        when=["continuity-handoff"],
        context_include=["continuity"],
        context_exclude=[],
        max_runtime_seconds=120,
        max_depth=1,
        max_risk="local-write",
        required_return_evidence=["notes"],
        escalation={},
    )

    validation = validate_graph_draft({"nodes": {k: v.__dict__ for k, v in nodes.items()}, "edges": [edge.__dict__]})

    assert validation["ok"] is False
    assert any(item["scope"] == "continuity" and item["severity"] == "blocker" for item in validation["findings"])


def test_host_mismatch_is_blocker() -> None:
    payload = {
        "nodes": {
            "default": ProfileNode("default", "orchestrator", ["coordination"], ["mac"], "coordination", [], [], []).__dict__,
            "uxdesigner": _node(allowed_hosts=["linux-box"]).__dict__,
        },
        "edges": [DelegationEdge("default", "uxdesigner", ["visual-critique"], ["ui-ux"], [], 120, 1, "local-write", ["screenshot"], {}).__dict__],
    }

    validation = validate_graph_draft(payload)

    assert validation["ok"] is False
    assert any(item["scope"] == "host-boundary" and item["severity"] == "blocker" for item in validation["findings"])


def test_good_fit_has_required_output_keys_and_high_score() -> None:
    result = evaluate_profile(
        profile="uxdesigner",
        intent=_intent(),
        node=_node(),
        available_skills=["claude-design"],
        available_toolsets=["browser", "vision", "file"],
    )

    expected = {
        "fit_score",
        "missing_capabilities",
        "over_broad_capabilities",
        "authority_findings",
        "host_boundary_findings",
        "continuity_findings",
        "prompt_pressure_findings",
        "recommended_changes",
    }
    assert expected <= set(result)
    assert result["fit_score"] >= 90


if __name__ == "__main__":
    test_missing_required_skill_yields_missing_finding()
    test_read_only_profile_with_power_toolsets_warns_over_broad()
    test_protected_continuity_route_to_specialist_is_blocker()
    test_host_mismatch_is_blocker()
    test_good_fit_has_required_output_keys_and_high_score()
    print("All tests passed!")
