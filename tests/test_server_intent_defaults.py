from __future__ import annotations

import sys
sys.path.insert(0, "webui")

from server import intent_for_profile


def test_orchestrator_role_defaults_to_workbench_contract() -> None:
    intent = intent_for_profile("orchestrator")

    assert intent.profile == "orchestrator"
    assert intent.role == "orchestrator"
    assert intent.domain == "profile-management"
    assert intent.authority_boundary["max_risk"] == "coordination"
    assert "delegate protected continuity" in intent.forbidden
    assert "delegation log" in intent.evidence_required
    assert intent.source == "inferred-orchestrator-default"
