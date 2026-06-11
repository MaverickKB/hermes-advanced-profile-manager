from __future__ import annotations

import sys
sys.path.insert(0, "webui")

from delegation_graph import (
    ProfileNode,
    DelegationEdge,
    DelegationGraph,
    validate_delegation_graph,
    ACCEPTED_ROLES,
    ACCEPTED_RISK_VALUES,
    PROTECTED_DOMAINS,
    DEFAULT_MAX_DEPTH,
)


def _base_node(name: str, role: str, max_risk: str, allowed_hosts: list[str] | None = None) -> ProfileNode:
    return ProfileNode(
        name=name,
        role=role,
        domains=["coordination"],
        allowed_hosts=allowed_hosts or ["local"],
        max_risk=max_risk,
        required_skills=[],
        required_toolsets=[],
        protected_domains=[],
    )


def _default_node() -> ProfileNode:
    return ProfileNode(
        name="default",
        role="orchestrator",
        domains=["coordination", "profile-management"],
        allowed_hosts=["local"],
        max_risk="coordination",
        required_skills=["hermes-agent", "aethermind-continuity"],
        required_toolsets=["memory", "session_search"],
        protected_domains=["continuity", "project-memory", "world-state"],
    )


def _uxdesigner_node() -> ProfileNode:
    return ProfileNode(
        name="uxdesigner",
        role="specialist",
        domains=["ux", "visual-design"],
        allowed_hosts=["local"],
        max_risk="local-write",
        required_skills=["claude-design", "design-md"],
        required_toolsets=["browser", "vision", "file"],
        protected_domains=[],
    )


def _codecritic_node() -> ProfileNode:
    return ProfileNode(
        name="codecritic",
        role="reviewer",
        domains=["code-review", "security"],
        allowed_hosts=["local"],
        max_risk="read-only",
        required_skills=["github-code-review", "systematic-debugging"],
        required_toolsets=["terminal", "file", "session_search"],
        protected_domains=[],
    )


def test_valid_default_to_uxdesigner_edge() -> None:
    nodes = {
        "default": _default_node(),
        "uxdesigner": _uxdesigner_node(),
    }
    edges = [
        DelegationEdge(
            source="default",
            target="uxdesigner",
            when=["visual-critique", "design-review"],
            context_include=["ux", "visual-design"],
            context_exclude=["continuity", "project-memory"],
            max_runtime_seconds=120,
            max_depth=1,
            max_risk="local-write",
            required_return_evidence=["screenshot", "critique notes"],
            escalation={},
        )
    ]
    graph = DelegationGraph(nodes=nodes, edges=edges)
    assert len(graph.edges) == 1
    assert graph.edges[0].source == "default"
    assert graph.edges[0].target == "uxdesigner"


def test_missing_target_fails() -> None:
    nodes = {"default": _default_node()}
    edges = [
        DelegationEdge(
            source="default",
            target="nonexistent",
            when=["test"],
            context_include=["ux"],
            context_exclude=[],
            max_runtime_seconds=60,
            max_depth=1,
            max_risk="local-write",
            required_return_evidence=[],
            escalation={},
        )
    ]
    try:
        DelegationGraph(nodes=nodes, edges=edges)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "not found in nodes" in str(e)


def test_authority_escalation_fails() -> None:
    nodes = {
        "default": _default_node(),
        "uxdesigner": ProfileNode(
            name="uxdesigner",
            role="specialist",
            domains=["ux"],
            allowed_hosts=["local"],
            max_risk="read-only",  # lower than caller's
            required_skills=[],
            required_toolsets=[],
            protected_domains=[],
        ),
    }
    edges = [
        DelegationEdge(
            source="default",
            target="uxdesigner",
            when=["test"],
            context_include=["ux"],
            context_exclude=[],
            max_runtime_seconds=60,
            max_depth=1,
            max_risk="coordination",  # exceeds target's read-only
            required_return_evidence=[],
            escalation={},
        )
    ]
    try:
        DelegationGraph(nodes=nodes, edges=edges)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "exceeds target node max_risk" in str(e)


def test_continuity_offload_fails() -> None:
    nodes = {
        "default": _default_node(),
        "uxdesigner": _uxdesigner_node(),
    }
    edges = [
        DelegationEdge(
            source="default",
            target="uxdesigner",
            when=["continuity-task"],
            context_include=["continuity"],  # protected domain
            context_exclude=[],
            max_runtime_seconds=60,
            max_depth=1,
            max_risk="local-write",
            required_return_evidence=["heartbeat"],
            escalation={},
        )
    ]
    try:
        DelegationGraph(nodes=nodes, edges=edges)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "protected domain" in str(e)
        assert "continuity" in str(e)


def test_project_memory_offload_fails() -> None:
    nodes = {
        "default": _default_node(),
        "uxdesigner": _uxdesigner_node(),
    }
    edges = [
        DelegationEdge(
            source="default",
            target="uxdesigner",
            when=["memory-task"],
            context_include=["project-memory"],
            context_exclude=[],
            max_runtime_seconds=60,
            max_depth=1,
            max_risk="local-write",
            required_return_evidence=["memory log"],
            escalation={},
        )
    ]
    try:
        DelegationGraph(nodes=nodes, edges=edges)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "protected domain" in str(e)
        assert "project-memory" in str(e)


def test_world_state_offload_fails() -> None:
    nodes = {
        "default": _default_node(),
        "uxdesigner": _uxdesigner_node(),
    }
    edges = [
        DelegationEdge(
            source="default",
            target="uxdesigner",
            when=["state-task"],
            context_include=["world-state"],
            context_exclude=[],
            max_runtime_seconds=60,
            max_depth=1,
            max_risk="local-write",
            required_return_evidence=["state dump"],
            escalation={},
        )
    ]
    try:
        DelegationGraph(nodes=nodes, edges=edges)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "protected domain" in str(e)
        assert "world-state" in str(e)


def test_host_mismatch_fails() -> None:
    nodes = {
        "default": ProfileNode(
            name="default",
            role="orchestrator",
            domains=["coordination"],
            allowed_hosts=["host-a"],
            max_risk="coordination",
            required_skills=[],
            required_toolsets=[],
            protected_domains=[],
        ),
        "uxdesigner": ProfileNode(
            name="uxdesigner",
            role="specialist",
            domains=["ux"],
            allowed_hosts=["host-b"],  # no overlap
            max_risk="local-write",
            required_skills=[],
            required_toolsets=[],
            protected_domains=[],
        ),
    }
    edges = [
        DelegationEdge(
            source="default",
            target="uxdesigner",
            when=["test"],
            context_include=["ux"],
            context_exclude=[],
            max_runtime_seconds=60,
            max_depth=1,
            max_risk="local-write",
            required_return_evidence=[],
            escalation={},
        )
    ]
    try:
        DelegationGraph(nodes=nodes, edges=edges)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "host mismatch" in str(e)


def test_host_match_passes() -> None:
    nodes = {
        "default": ProfileNode(
            name="default",
            role="orchestrator",
            domains=["coordination"],
            allowed_hosts=["local", "remote"],
            max_risk="coordination",
            required_skills=[],
            required_toolsets=[],
            protected_domains=[],
        ),
        "uxdesigner": ProfileNode(
            name="uxdesigner",
            role="specialist",
            domains=["ux"],
            allowed_hosts=["local"],
            max_risk="local-write",
            required_skills=[],
            required_toolsets=[],
            protected_domains=[],
        ),
    }
    edges = [
        DelegationEdge(
            source="default",
            target="uxdesigner",
            when=["test"],
            context_include=["ux"],
            context_exclude=[],
            max_runtime_seconds=60,
            max_depth=1,
            max_risk="local-write",
            required_return_evidence=[],
            escalation={},
        )
    ]
    graph = DelegationGraph(nodes=nodes, edges=edges)
    assert len(graph.edges) == 1


def test_external_service_host_mismatch_allowed() -> None:
    nodes = {
        "default": ProfileNode(
            name="default",
            role="orchestrator",
            domains=["coordination", "external-service"],
            allowed_hosts=["local"],
            max_risk="coordination",
            required_skills=[],
            required_toolsets=[],
            protected_domains=[],
        ),
        "external_api": ProfileNode(
            name="external_api",
            role="specialist",
            domains=["external-service"],
            allowed_hosts=["api.example.com"],
            max_risk="remote-write",
            required_skills=[],
            required_toolsets=[],
            protected_domains=[],
        ),
    }
    edges = [
        DelegationEdge(
            source="default",
            target="external_api",
            when=["api-call"],
            context_include=["data-fetch"],
            context_exclude=[],
            max_runtime_seconds=30,
            max_depth=1,
            max_risk="remote-write",
            required_return_evidence=["response"],
            escalation={},
        )
    ]
    graph = DelegationGraph(nodes=nodes, edges=edges)
    assert len(graph.edges) == 1


def test_max_depth_bounded() -> None:
    nodes = {
        "default": _default_node(),
        "uxdesigner": _uxdesigner_node(),
    }
    edges = [
        DelegationEdge(
            source="default",
            target="uxdesigner",
            when=["test"],
            context_include=["ux"],
            context_exclude=[],
            max_runtime_seconds=60,
            max_depth=DEFAULT_MAX_DEPTH,
            max_risk="local-write",
            required_return_evidence=[],
            escalation={},
        )
    ]
    graph = DelegationGraph(nodes=nodes, edges=edges)
    assert graph.edges[0].max_depth == DEFAULT_MAX_DEPTH

    # Test that max_depth > DEFAULT_MAX_DEPTH is allowed for escalation paths (needs target with higher max_risk)
    nodes_for_escalation = {
        "default": _default_node(),
        "manager": ProfileNode(
            name="manager",
            role="orchestrator",
            domains=["coordination"],
            allowed_hosts=["local"],
            max_risk="coordination",
            required_skills=[],
            required_toolsets=[],
            protected_domains=[],
        ),
    }
    edges_deep = [
        DelegationEdge(
            source="default",
            target="manager",
            when=["escalation"],
            context_include=["coordination"],
            context_exclude=[],
            max_runtime_seconds=300,
            max_depth=3,
            max_risk="coordination",
            required_return_evidence=["full report"],
            escalation={"fallback": "reviewer"},
        )
    ]
    graph_deep = DelegationGraph(nodes=nodes_for_escalation, edges=edges_deep)
    assert graph_deep.edges[0].max_depth == 3


def test_max_depth_zero_fails() -> None:
    nodes = {
        "default": _default_node(),
        "uxdesigner": _uxdesigner_node(),
    }
    try:
        edges = [
            DelegationEdge(
                source="default",
                target="uxdesigner",
                when=["test"],
                context_include=["ux"],
                context_exclude=[],
                max_runtime_seconds=60,
                max_depth=0,
                max_risk="local-write",
                required_return_evidence=[],
                escalation={},
            )
        ]
        DelegationGraph(nodes=nodes, edges=edges)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "max_depth must be positive" in str(e)


def test_serialization_round_trip() -> None:
    nodes = {
        "default": _default_node(),
        "uxdesigner": _uxdesigner_node(),
        "codecritic": _codecritic_node(),
    }
    edges = [
        DelegationEdge(
            source="default",
            target="uxdesigner",
            when=["visual-critique"],
            context_include=["ux", "visual-design"],
            context_exclude=["continuity", "project-memory"],
            max_runtime_seconds=120,
            max_depth=1,
            max_risk="local-write",
            required_return_evidence=["screenshot", "critique notes"],
            escalation={"on_failure": "codecritic"},
        ),
        DelegationEdge(
            source="default",
            target="codecritic",
            when=["code-review"],
            context_include=["code", "security"],
            context_exclude=[],
            max_runtime_seconds=180,
            max_depth=1,
            max_risk="read-only",
            required_return_evidence=["review findings"],
            escalation={},
        ),
    ]
    original = DelegationGraph(nodes=nodes, edges=edges)
    data = original.to_dict()
    restored = DelegationGraph.from_dict(data)
    assert len(restored.nodes) == 3
    assert len(restored.edges) == 2
    assert restored.nodes["default"].role == "orchestrator"
    assert restored.nodes["uxdesigner"].role == "specialist"
    assert restored.edges[0].source == "default"
    assert restored.edges[0].target == "uxdesigner"
    assert restored.edges[0].escalation.get("on_failure") == "codecritic"


def test_validate_delegation_graph_function() -> None:
    data = {
        "nodes": {
            "default": {
                "name": "default",
                "role": "orchestrator",
                "domains": ["coordination"],
                "allowed_hosts": ["local"],
                "max_risk": "coordination",
                "required_skills": [],
                "required_toolsets": [],
                "protected_domains": ["continuity"],
            },
            "uxdesigner": {
                "name": "uxdesigner",
                "role": "specialist",
                "domains": ["ux"],
                "allowed_hosts": ["local"],
                "max_risk": "local-write",
                "required_skills": [],
                "required_toolsets": [],
                "protected_domains": [],
            },
        },
        "edges": [
            {
                "source": "default",
                "target": "uxdesigner",
                "when": ["test"],
                "context_include": ["ux"],
                "context_exclude": [],
                "max_runtime_seconds": 60,
                "max_depth": 1,
                "max_risk": "local-write",
                "required_return_evidence": [],
                "escalation": {},
            }
        ],
    }
    graph = validate_delegation_graph(data)
    assert isinstance(graph, DelegationGraph)
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1


def test_all_accepted_roles_allowed_in_node() -> None:
    for role in ACCEPTED_ROLES:
        node = ProfileNode(
            name=f"test-{role}",
            role=role,
            domains=["test"],
            allowed_hosts=["local"],
            max_risk="read-only",
            required_skills=[],
            required_toolsets=[],
            protected_domains=[],
        )
        assert node.role == role


def test_all_accepted_risk_values_allowed() -> None:
    for risk in ACCEPTED_RISK_VALUES:
        node = ProfileNode(
            name="test",
            role="operator",
            domains=["test"],
            allowed_hosts=["local"],
            max_risk=risk,
            required_skills=[],
            required_toolsets=[],
            protected_domains=[],
        )
        assert node.max_risk == risk


if __name__ == "__main__":
    test_valid_default_to_uxdesigner_edge()
    test_missing_target_fails()
    test_authority_escalation_fails()
    test_continuity_offload_fails()
    test_project_memory_offload_fails()
    test_world_state_offload_fails()
    test_host_mismatch_fails()
    test_host_match_passes()
    test_external_service_host_mismatch_allowed()
    test_max_depth_bounded()
    test_max_depth_zero_fails()
    test_serialization_round_trip()
    test_validate_delegation_graph_function()
    test_all_accepted_roles_allowed_in_node()
    test_all_accepted_risk_values_allowed()
    print("All tests passed!")