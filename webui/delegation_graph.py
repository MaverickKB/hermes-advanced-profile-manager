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

ACCEPTED_RISK_VALUES = frozenset({
    "read-only",
    "local-write",
    "remote-write",
    "home-control",
    "coordination",
})

PROTECTED_DOMAINS = frozenset({
    "continuity",
    "project-memory",
    "world-state",
})

DEFAULT_MAX_DEPTH = 1


@dataclass
class ProfileNode:
    name: str
    role: str
    domains: list[str]
    allowed_hosts: list[str]
    max_risk: str
    required_skills: list[str]
    required_toolsets: list[str]
    protected_domains: list[str]

    def __post_init__(self) -> None:
        if self.role not in ACCEPTED_ROLES:
            raise ValueError(f"role '{self.role}' not in accepted roles: {sorted(ACCEPTED_ROLES)}")
        if self.max_risk not in ACCEPTED_RISK_VALUES:
            raise ValueError(f"max_risk '{self.max_risk}' not in accepted values: {sorted(ACCEPTED_RISK_VALUES)}")


@dataclass
class DelegationEdge:
    source: str
    target: str
    when: list[str]
    context_include: list[str]
    context_exclude: list[str]
    max_runtime_seconds: int
    max_depth: int
    max_risk: str
    required_return_evidence: list[str]
    escalation: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_risk not in ACCEPTED_RISK_VALUES:
            raise ValueError(f"max_risk '{self.max_risk}' not in accepted values: {sorted(ACCEPTED_RISK_VALUES)}")
        if self.max_runtime_seconds <= 0:
            raise ValueError("max_runtime_seconds must be positive")
        if self.max_depth <= 0:
            raise ValueError("max_depth must be positive")
        if self.max_depth > DEFAULT_MAX_DEPTH and self.max_risk in {"home-control", "coordination"}:
            pass  # escalation paths may use deeper delegation
        if not self.source or not self.target:
            raise ValueError("source and target are required")


@dataclass
class DelegationGraph:
    nodes: dict[str, ProfileNode]
    edges: list[DelegationEdge]

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        node_names = set(self.nodes.keys())
        for edge in self.edges:
            if edge.source not in node_names:
                raise ValueError(f"edge source '{edge.source}' not found in nodes")
            if edge.target not in node_names:
                raise ValueError(f"edge target '{edge.target}' not found in nodes")
            source_node = self.nodes[edge.source]
            target_node = self.nodes[edge.target]
            if self._risk_rank(edge.max_risk) > self._risk_rank(target_node.max_risk):
                raise ValueError(f"edge max_risk '{edge.max_risk}' exceeds target node max_risk '{target_node.max_risk}'")
            for domain in edge.context_include:
                if domain in PROTECTED_DOMAINS and target_node.role != "protected-continuity":
                    raise ValueError(f"protected domain '{domain}' cannot be delegated to non-protected role '{target_node.role}'")
            source_hosts = set(source_node.allowed_hosts)
            target_hosts = set(target_node.allowed_hosts)
            if source_hosts and target_hosts and not source_hosts & target_hosts:
                if "external-service" not in source_node.domains and "external-service" not in target_node.domains:
                    raise ValueError(f"host mismatch: source hosts {sorted(source_hosts)} do not intersect target hosts {sorted(target_hosts)}")
            if edge.max_depth <= 0:
                raise ValueError("edge max_depth must be positive")

    def _risk_rank(self, risk: str) -> int:
        rank = {
            "read-only": 0,
            "local-write": 1,
            "bounded-write": 2,
            "remote-write": 3,
            "coordination": 4,
            "home-control": 5,
        }
        return rank.get(risk, -1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {name: asdict(node) for name, node in self.nodes.items()},
            "edges": [asdict(edge) for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DelegationGraph:
        nodes = {name: ProfileNode(**node_data) for name, node_data in data.get("nodes", {}).items()}
        edges = [DelegationEdge(**edge_data) for edge_data in data.get("edges", [])]
        return cls(nodes=nodes, edges=edges)


def validate_delegation_graph(data: dict[str, Any]) -> DelegationGraph:
    return DelegationGraph.from_dict(data)