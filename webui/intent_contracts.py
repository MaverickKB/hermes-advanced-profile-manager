from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


ACCEPTED_ROLES = frozenset({
    "operator",
    "orchestrator",
    "specialist",
    "reviewer",
    "worker",
    "fallback",
    "protected-continuity",
})

ACCEPTED_AUTHORITY_VALUES = frozenset({
    "read-only",
    "local-write",
    "remote-write",
    "home-control",
    "coordination",
})


@dataclass
class IntentContract:
    profile: str
    role: str
    domain: str
    mission: str
    tasks: list[str]
    success_criteria: list[str]
    forbidden: list[str]
    authority_boundary: dict[str, Any]
    evidence_required: list[str]
    confidence: float = 0.0
    source: str = "inferred"

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if self.role not in ACCEPTED_ROLES:
            raise ValueError(f"role '{self.role}' not in accepted roles: {sorted(ACCEPTED_ROLES)}")

        max_risk = self.authority_boundary.get("max_risk")
        if max_risk is not None and max_risk not in ACCEPTED_AUTHORITY_VALUES:
            raise ValueError(f"authority_boundary.max_risk '{max_risk}' not in accepted values: {sorted(ACCEPTED_AUTHORITY_VALUES)}")

        if not self.mission.strip() and self.source != "inferred":
            raise ValueError("missing mission requires source='inferred'")

        if not self.mission.strip() and self.confidence > 0.3:
            raise ValueError("low confidence (<=0.3) required when mission is missing/inferred")

        if self.role == "protected-continuity":
            for key in ("continuity", "project-memory", "world-state"):
                if key in self.authority_boundary.get("delegated_domains", []):
                    raise ValueError(f"protected-continuity role cannot delegate '{key}' authority to non-protected roles")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentContract:
        return cls(**data)


def validate_intent_contract(data: dict[str, Any]) -> IntentContract:
    return IntentContract.from_dict(data)