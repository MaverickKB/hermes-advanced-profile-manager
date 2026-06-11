from __future__ import annotations

import sys
sys.path.insert(0, "webui")

from intent_contracts import IntentContract, validate_intent_contract, ACCEPTED_ROLES, ACCEPTED_AUTHORITY_VALUES


def test_valid_operator_contract() -> None:
    contract = IntentContract(
        profile="default",
        role="operator",
        domain="profile-management",
        mission="Manage profile lifecycle with safe apply",
        tasks=["create", "update", "validate"],
        success_criteria=["all changes validated", "backup exists"],
        forbidden=["direct writes without diff"],
        authority_boundary={"max_risk": "local-write", "delegated_domains": []},
        evidence_required=["diff", "audit"],
    )
    assert contract.role == "operator"
    assert contract.confidence == 0.0
    assert contract.source == "inferred"
    data = contract.to_dict()
    assert data["profile"] == "default"


def test_valid_orchestrator_contract() -> None:
    contract = IntentContract(
        profile="default",
        role="orchestrator",
        domain="multi-agent-coordination",
        mission="Coordinate specialist profiles for complex tasks",
        tasks=["plan", "delegate", "review"],
        success_criteria=["all subtasks completed", "no authority escalation"],
        forbidden=["direct profile writes", "bypassing delegation graph"],
        authority_boundary={"max_risk": "coordination", "delegated_domains": ["ux", "code", "research"]},
        evidence_required=["delegation log", "return evidence"],
        confidence=0.85,
        source="explicit",
    )
    assert contract.role == "orchestrator"
    assert contract.confidence == 0.85
    assert contract.source == "explicit"


def test_invalid_role_rejected() -> None:
    try:
        IntentContract(
            profile="test",
            role="invalid-role",
            domain="test",
            mission="test",
            tasks=[],
            success_criteria=[],
            forbidden=[],
            authority_boundary={"max_risk": "read-only"},
            evidence_required=[],
        )
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "invalid-role" in str(e)
        assert "accepted roles" in str(e)


def test_invalid_max_risk_rejected() -> None:
    try:
        IntentContract(
            profile="test",
            role="operator",
            domain="test",
            mission="test",
            tasks=[],
            success_criteria=[],
            forbidden=[],
            authority_boundary={"max_risk": "super-admin"},
            evidence_required=[],
        )
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "super-admin" in str(e)
        assert "accepted values" in str(e)


def test_missing_mission_requires_inferred_source() -> None:
    try:
        IntentContract(
            profile="test",
            role="operator",
            domain="test",
            mission="",
            tasks=[],
            success_criteria=[],
            forbidden=[],
            authority_boundary={"max_risk": "read-only"},
            evidence_required=[],
            source="explicit",
        )
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "missing mission requires source='inferred'" in str(e)


def test_missing_mission_requires_low_confidence() -> None:
    try:
        IntentContract(
            profile="test",
            role="operator",
            domain="test",
            mission="",
            tasks=[],
            success_criteria=[],
            forbidden=[],
            authority_boundary={"max_risk": "read-only"},
            evidence_required=[],
            source="inferred",
            confidence=0.5,
        )
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "low confidence" in str(e)


def test_protected_continuity_rejects_delegation_of_continuity() -> None:
    try:
        IntentContract(
            profile="ember",
            role="protected-continuity",
            domain="continuity",
            mission="Guard continuity and memory",
            tasks=["watch", "escalate"],
            success_criteria=["no continuity loss"],
            forbidden=["delegate continuity"],
            authority_boundary={"max_risk": "home-control", "delegated_domains": ["continuity"]},
            evidence_required=["heartbeat log"],
        )
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "protected-continuity role cannot delegate 'continuity'" in str(e)


def test_protected_continuity_rejects_delegation_of_project_memory() -> None:
    try:
        IntentContract(
            profile="ember",
            role="protected-continuity",
            domain="continuity",
            mission="Guard continuity and memory",
            tasks=["watch", "escalate"],
            success_criteria=["no continuity loss"],
            forbidden=["delegate continuity"],
            authority_boundary={"max_risk": "home-control", "delegated_domains": ["project-memory"]},
            evidence_required=["heartbeat log"],
        )
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "protected-continuity role cannot delegate 'project-memory'" in str(e)


def test_protected_continuity_rejects_delegation_of_world_state() -> None:
    try:
        IntentContract(
            profile="ember",
            role="protected-continuity",
            domain="continuity",
            mission="Guard continuity and memory",
            tasks=["watch", "escalate"],
            success_criteria=["no continuity loss"],
            forbidden=["delegate continuity"],
            authority_boundary={"max_risk": "home-control", "delegated_domains": ["world-state"]},
            evidence_required=["heartbeat log"],
        )
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "protected-continuity role cannot delegate 'world-state'" in str(e)


def test_protected_continuity_allows_other_domains() -> None:
    contract = IntentContract(
        profile="ember",
        role="protected-continuity",
        domain="continuity",
        mission="Guard continuity and memory",
        tasks=["watch", "escalate"],
        success_criteria=["no continuity loss"],
        forbidden=["delegate continuity"],
        authority_boundary={"max_risk": "home-control", "delegated_domains": ["ux", "code"]},
        evidence_required=["heartbeat log"],
    )
    assert contract.role == "protected-continuity"
    assert "ux" in contract.authority_boundary["delegated_domains"]


def test_serialization_round_trip() -> None:
    original = IntentContract(
        profile="default",
        role="orchestrator",
        domain="coordination",
        mission="Test mission",
        tasks=["a", "b"],
        success_criteria=["done"],
        forbidden=["bad"],
        authority_boundary={"max_risk": "coordination", "delegated_domains": ["ux"]},
        evidence_required=["log"],
        confidence=0.7,
        source="explicit",
    )
    data = original.to_dict()
    restored = IntentContract.from_dict(data)
    assert restored.profile == original.profile
    assert restored.role == original.role
    assert restored.domain == original.domain
    assert restored.mission == original.mission
    assert restored.tasks == original.tasks
    assert restored.success_criteria == original.success_criteria
    assert restored.forbidden == original.forbidden
    assert restored.authority_boundary == original.authority_boundary
    assert restored.evidence_required == original.evidence_required
    assert restored.confidence == original.confidence
    assert restored.source == original.source


def test_validate_intent_contract_function() -> None:
    data = {
        "profile": "test",
        "role": "specialist",
        "domain": "test",
        "mission": "Test mission",
        "tasks": ["task1"],
        "success_criteria": ["criteria"],
        "forbidden": [],
        "authority_boundary": {"max_risk": "local-write"},
        "evidence_required": ["evidence"],
    }
    contract = validate_intent_contract(data)
    assert isinstance(contract, IntentContract)
    assert contract.role == "specialist"


def test_all_accepted_roles_allowed() -> None:
    for role in ACCEPTED_ROLES:
        contract = IntentContract(
            profile="test",
            role=role,
            domain="test",
            mission="Test mission",
            tasks=[],
            success_criteria=[],
            forbidden=[],
            authority_boundary={"max_risk": "read-only"},
            evidence_required=[],
        )
        assert contract.role == role


def test_all_accepted_authority_values_allowed() -> None:
    for authority in ACCEPTED_AUTHORITY_VALUES:
        contract = IntentContract(
            profile="test",
            role="operator",
            domain="test",
            mission="Test mission",
            tasks=[],
            success_criteria=[],
            forbidden=[],
            authority_boundary={"max_risk": authority},
            evidence_required=[],
        )
        assert contract.authority_boundary["max_risk"] == authority


if __name__ == "__main__":
    test_valid_operator_contract()
    test_valid_orchestrator_contract()
    test_invalid_role_rejected()
    test_invalid_max_risk_rejected()
    test_missing_mission_requires_inferred_source()
    test_missing_mission_requires_low_confidence()
    test_protected_continuity_rejects_delegation_of_continuity()
    test_protected_continuity_rejects_delegation_of_project_memory()
    test_protected_continuity_rejects_delegation_of_world_state()
    test_protected_continuity_allows_other_domains()
    test_serialization_round_trip()
    test_validate_intent_contract_function()
    test_all_accepted_roles_allowed()
    test_all_accepted_authority_values_allowed()
    print("All tests passed!")