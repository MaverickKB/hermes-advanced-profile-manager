from __future__ import annotations

import sys
sys.path.insert(0, "webui")

from change_set import ProfileChangeSet, Finding, new_change_set


def test_new_change_set_basic() -> None:
    cs = new_change_set("test-workflow", "Test Title", ["profile-a"], "Test summary")
    assert cs.workflow == "test-workflow"
    assert cs.title == "Test Title"
    assert cs.target_profiles == ["profile-a"]
    assert cs.summary == "Test summary"
    assert cs.id.startswith("test-workflow-")


def test_change_set_to_dict_includes_all_fields() -> None:
    cs = new_change_set("test", "Test", ["p1"], "summary")
    cs.generated_files.append({"path": "test.yaml", "kind": "config"})
    cs.config_patches.append({"op": "merge", "path": "/a", "value": 1})
    cs.skill_assignments.append({"profile": "p1", "recommended_enabled": ["s1"]})
    cs.findings.append(Finding("info", "test", "message"))
    cs.validation.append({"check": "pass"})
    cs.diff = "--- a\n+++ b\n"
    cs.backup_plan.append({"profile": "p1", "action": "backup"})
    cs.audit_preview.append({"event": "test"})

    # Phase A fields
    cs.intent_contracts.append({"profile": "p1", "role": "operator"})
    cs.delegation_edges.append({"source": "p1", "target": "p2"})
    cs.authority_changes.append({"profile": "p1", "change": "risk"})
    cs.fit_evaluations.append({"profile": "p1", "score": 90})

    data = cs.to_dict()

    # Original fields
    assert data["workflow"] == "test"
    assert data["generated_files"] == [{"path": "test.yaml", "kind": "config"}]
    assert data["config_patches"] == [{"op": "merge", "path": "/a", "value": 1}]
    assert len(data["skill_assignments"]) == 1
    assert len(data["findings"]) == 1
    assert data["findings"][0]["severity"] == "info"
    assert data["validation"] == [{"check": "pass"}]
    assert data["diff"] == "--- a\n+++ b\n"
    assert data["backup_plan"] == [{"profile": "p1", "action": "backup"}]
    assert data["audit_preview"] == [{"event": "test"}]

    # Phase A fields
    assert data["intent_contracts"] == [{"profile": "p1", "role": "operator"}]
    assert data["delegation_edges"] == [{"source": "p1", "target": "p2"}]
    assert data["authority_changes"] == [{"profile": "p1", "change": "risk"}]
    assert data["fit_evaluations"] == [{"profile": "p1", "score": 90}]


def test_backward_compatibility_existing_purpose_planner_output() -> None:
    """Simulate the output from purpose_planner.plan_profile_for_purpose"""
    cs = new_change_set("build-profile-for-purpose", "Build operator profile for profile-management", ["new-profile"], "Generate an operator profile plan for profile-management work with tasks: create, update, validate.")
    cs.config_patches.append({
        "op": "merge",
        "path": "/profile_metadata",
        "value": {"domain": "profile-management", "role": "operator", "tasks": ["create", "update", "validate"], "risk": "local-write", "purpose": "Generate an operator profile plan for profile-management work with tasks: create, update, validate."},
    })
    cs.skill_assignments.append({"profile": "new-profile", "recommended_enabled": ["systematic-debugging", "plan"], "missing": []})
    cs.provider_changes.append({"profile": "new-profile", "note": "Use selected provider/model from Model & toolsets workflow; no invented default."})
    cs.prompt_changes.append({"profile": "new-profile", "source": "SOUL.md or system prompt", "recommended_sections": ["Mission", "Repo grounding", "Testing and commit discipline"]})
    cs.generated_files.append({"path": "profiles/new-profile/SOUL.md", "kind": "identity-draft", "preview": "# new-profile\n\nRole: operator\nDomain: profile-management\nTasks: create, update, validate\n\n## Operating posture\n- Use selected skills and tools for this profile's purpose.\n- Keep changes behind validation/diff/apply.\n"})
    cs.backup_plan.append({"profile": "new-profile", "action": "backup config.yaml before any write"})
    cs.audit_preview.append({"event": "plan_profile_for_purpose", "profile": "new-profile", "domain": "profile-management", "role": "operator"})
    cs.findings.append(Finding("info", "workflow", "This is a generated plan, not a direct write. Review, validate, diff, then apply through the shared safe-apply path."))

    data = cs.to_dict()

    # Verify all purpose_planner fields are present
    assert data["workflow"] == "build-profile-for-purpose"
    assert len(data["config_patches"]) == 1
    assert len(data["skill_assignments"]) == 1
    assert len(data["provider_changes"]) == 1
    assert len(data["prompt_changes"]) == 1
    assert len(data["generated_files"]) == 1
    assert len(data["backup_plan"]) == 1
    assert len(data["audit_preview"]) == 1
    assert len(data["findings"]) == 1

    # Phase A fields should be empty by default (backward compatible)
    assert data["intent_contracts"] == []
    assert data["delegation_edges"] == []
    assert data["authority_changes"] == []
    assert data["fit_evaluations"] == []


def test_advanced_workbench_fields_can_be_populated() -> None:
    cs = new_change_set("orchestrator-workbench", "Orchestrator workbench plan", ["default", "uxdesigner"], "Multi-profile delegation plan")
    
    # Add intent contracts
    cs.intent_contracts.append({
        "profile": "default",
        "role": "orchestrator",
        "domain": "coordination",
        "mission": "Coordinate specialist profiles",
        "tasks": ["plan", "delegate", "review"],
        "success_criteria": ["all tasks complete"],
        "forbidden": ["direct writes"],
        "authority_boundary": {"max_risk": "coordination", "delegated_domains": ["ux", "code"]},
        "evidence_required": ["delegation log"],
        "confidence": 0.9,
        "source": "explicit",
    })
    cs.intent_contracts.append({
        "profile": "uxdesigner",
        "role": "specialist",
        "domain": "ux",
        "mission": "Provide visual critique",
        "tasks": ["review", "critique"],
        "success_criteria": ["actionable feedback"],
        "forbidden": ["implement code"],
        "authority_boundary": {"max_risk": "local-write", "delegated_domains": []},
        "evidence_required": ["screenshot", "notes"],
        "confidence": 0.85,
        "source": "inferred",
    })

    # Add delegation edges
    cs.delegation_edges.append({
        "source": "default",
        "target": "uxdesigner",
        "when": ["visual-critique"],
        "context_include": ["ux", "visual-design"],
        "context_exclude": ["continuity"],
        "max_runtime_seconds": 120,
        "max_depth": 1,
        "max_risk": "local-write",
        "required_return_evidence": ["screenshot", "critique notes"],
        "escalation": {},
    })

    # Add authority changes
    cs.authority_changes.append({
        "profile": "uxdesigner",
        "change": "risk",
        "from": "read-only",
        "to": "local-write",
        "reason": "needs browser for visual critique",
    })

    # Add fit evaluations
    cs.fit_evaluations.append({
        "profile": "default",
        "fit_score": 95,
        "missing_capabilities": [],
        "over_broad_capabilities": [],
        "authority_findings": [],
        "host_boundary_findings": [],
        "continuity_findings": [],
        "prompt_pressure_findings": [],
        "recommended_changes": [],
    })
    cs.fit_evaluations.append({
        "profile": "uxdesigner",
        "fit_score": 88,
        "missing_capabilities": ["claude-design"],
        "over_broad_capabilities": [],
        "authority_findings": [],
        "host_boundary_findings": [],
        "continuity_findings": [],
        "prompt_pressure_findings": [],
        "recommended_changes": ["install claude-design skill"],
    })

    data = cs.to_dict()

    assert len(data["intent_contracts"]) == 2
    assert data["intent_contracts"][0]["profile"] == "default"
    assert data["intent_contracts"][0]["role"] == "orchestrator"
    assert data["intent_contracts"][1]["profile"] == "uxdesigner"
    assert data["intent_contracts"][1]["role"] == "specialist"

    assert len(data["delegation_edges"]) == 1
    assert data["delegation_edges"][0]["source"] == "default"
    assert data["delegation_edges"][0]["target"] == "uxdesigner"

    assert len(data["authority_changes"]) == 1
    assert data["authority_changes"][0]["profile"] == "uxdesigner"
    assert data["authority_changes"][0]["from"] == "read-only"
    assert data["authority_changes"][0]["to"] == "local-write"

    assert len(data["fit_evaluations"]) == 2
    assert data["fit_evaluations"][0]["profile"] == "default"
    assert data["fit_evaluations"][0]["fit_score"] == 95
    assert data["fit_evaluations"][1]["profile"] == "uxdesigner"
    assert data["fit_evaluations"][1]["fit_score"] == 88
    assert "claude-design" in data["fit_evaluations"][1]["missing_capabilities"]


def test_serialization_round_trip() -> None:
    cs = new_change_set("test", "Test", ["p1"], "summary")
    cs.intent_contracts.append({"profile": "p1", "role": "operator"})
    cs.delegation_edges.append({"source": "p1", "target": "p2"})
    cs.authority_changes.append({"profile": "p1", "change": "risk"})
    cs.fit_evaluations.append({"profile": "p1", "score": 90})

    data = cs.to_dict()
    # Reconstruct from dict
    cs2 = ProfileChangeSet(
        id=data["id"],
        title=data["title"],
        workflow=data["workflow"],
        target_profiles=data["target_profiles"],
        summary=data["summary"],
        generated_files=data["generated_files"],
        config_patches=data["config_patches"],
        skill_assignments=data["skill_assignments"],
        template_applications=data["template_applications"],
        prompt_changes=data["prompt_changes"],
        mcp_changes=data["mcp_changes"],
        provider_changes=data["provider_changes"],
        team_relationship_changes=data["team_relationship_changes"],
        findings=[Finding(**f) for f in data["findings"]],
        validation=data["validation"],
        diff=data["diff"],
        backup_plan=data["backup_plan"],
        audit_preview=data["audit_preview"],
        created_at=data["created_at"],
        intent_contracts=data["intent_contracts"],
        delegation_edges=data["delegation_edges"],
        authority_changes=data["authority_changes"],
        fit_evaluations=data["fit_evaluations"],
    )
    data2 = cs2.to_dict()
    assert data2 == data


if __name__ == "__main__":
    test_new_change_set_basic()
    test_change_set_to_dict_includes_all_fields()
    test_backward_compatibility_existing_purpose_planner_output()
    test_advanced_workbench_fields_can_be_populated()
    test_serialization_round_trip()
    print("All tests passed!")