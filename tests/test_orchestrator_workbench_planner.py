from __future__ import annotations

import sys
sys.path.insert(0, "webui")

from delegation_graph import DelegationEdge, DelegationGraph, ProfileNode
from intent_contracts import IntentContract
from purpose_planner import plan_orchestrator_workbench


def _intent() -> IntentContract:
    return IntentContract(
        profile="default",
        role="orchestrator",
        domain="profile-management",
        mission="Coordinate specialist profiles through bounded delegated work.",
        tasks=["plan", "delegate", "review"],
        success_criteria=["specialists return required evidence"],
        forbidden=["delegate continuity", "write real profiles from draft APIs"],
        authority_boundary={"max_risk": "coordination", "delegated_domains": ["ui-ux"]},
        evidence_required=["delegation log", "review findings"],
        confidence=0.92,
        source="explicit",
    )


def _graph() -> DelegationGraph:
    nodes = {
        "default": ProfileNode("default", "orchestrator", ["coordination", "profile-management"], ["local"], "coordination", ["hermes-agent"], ["profile_delegation", "session_search"], ["continuity"]),
        "uxdesigner": ProfileNode("uxdesigner", "specialist", ["ui-ux", "visual-design"], ["local"], "local-write", ["claude-design"], ["browser", "vision", "file"], []),
    }
    edges = [
        DelegationEdge(
            source="default",
            target="uxdesigner",
            when=["visual-critique", "workbench usability review"],
            context_include=["ui-ux", "visual-design"],
            context_exclude=["continuity", "project-memory"],
            max_runtime_seconds=900,
            max_depth=1,
            max_risk="local-write",
            required_return_evidence=["screenshot", "critique notes"],
            escalation={"on_blocker": "return-to-default"},
        )
    ]
    return DelegationGraph(nodes=nodes, edges=edges)


def test_plan_orchestrator_workbench_returns_profiles_changeset() -> None:
    cs = plan_orchestrator_workbench("default", _intent(), _graph())
    data = cs.to_dict()

    assert data["workflow"] == "orchestrator-delegation-intent"
    assert data["target_profiles"] == ["default", "uxdesigner"]
    assert data["intent_contracts"][0]["profile"] == "default"
    assert data["delegation_edges"][0]["source"] == "default"
    assert data["delegation_edges"][0]["target"] == "uxdesigner"


def test_plan_includes_sidecar_previews_and_recommendations() -> None:
    cs = plan_orchestrator_workbench("default", _intent(), _graph())
    data = cs.to_dict()

    generated = {item["kind"]: item for item in data["generated_files"]}
    assert "intent-sidecar-preview" in generated
    assert "delegation-graph-sidecar-preview" in generated
    assert "intent_contracts" in generated["intent-sidecar-preview"]["preview"]
    assert "delegation_edges" in generated["delegation-graph-sidecar-preview"]["preview"]
    assert data["config_patches"], "expected draft config/toolset recommendations"
    assert data["prompt_changes"], "expected prompt/SOUL section recommendation"
    assert data["skill_assignments"], "expected skill recommendations"


def test_plan_includes_validation_backup_and_audit_preview() -> None:
    cs = plan_orchestrator_workbench("default", _intent(), _graph())
    data = cs.to_dict()

    assert data["validation"]
    assert any(item["check"] == "delegation_graph" for item in data["validation"])
    assert data["backup_plan"]
    assert any(item["profile"] == "default" for item in data["backup_plan"])
    assert data["audit_preview"]
    assert any(item["event"] == "draft_orchestrator_workbench_plan" for item in data["audit_preview"])
    assert any("draft" in item["message"].lower() for item in data["findings"])


def test_plan_records_evaluator_output_for_each_node() -> None:
    cs = plan_orchestrator_workbench("default", _intent(), _graph())
    data = cs.to_dict()

    profiles = {item["profile"] for item in data["fit_evaluations"]}
    assert profiles == {"default", "uxdesigner"}
    for item in data["fit_evaluations"]:
        assert "fit_score" in item
        assert "missing_capabilities" in item
        assert "continuity_findings" in item


if __name__ == "__main__":
    test_plan_orchestrator_workbench_returns_profiles_changeset()
    test_plan_includes_sidecar_previews_and_recommendations()
    test_plan_includes_validation_backup_and_audit_preview()
    test_plan_records_evaluator_output_for_each_node()
    print("All tests passed!")
