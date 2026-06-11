"""Pair/team/orchestrator topology design.

Supports four topology modes (single, pair, team, orchestrator) with
specialists that may be existing profiles, inline-created drafts, adapted
duplicates, or declared future dependencies — without losing the primary
profile draft mid-flow.
"""
from __future__ import annotations

import os
from typing import Any

from change_set import Finding, ProfileChangeSet
from delegation_graph import ACCEPTED_RISK_VALUES, DelegationEdge, DelegationGraph, ProfileNode
from hermes_paths import profile_dir
from intent_contracts import IntentContract

TOPOLOGY_MODES = ("single", "pair", "team", "orchestrator")
PROTECTED_EXCLUDES = ["continuity", "project-memory", "world-state"]


def _specialist_node(spec: dict[str, Any], hosts: list[str]) -> ProfileNode:
    role = str(spec.get("role") or "specialist")
    if role not in {"specialist", "worker", "reviewer", "fallback"}:
        role = "specialist"
    risk = str(spec.get("max_risk") or "local-write")
    if risk not in ACCEPTED_RISK_VALUES:
        risk = "local-write"
    domains = [str(d) for d in (spec.get("domains") or []) if str(d).strip()] or [str(spec.get("domain") or "general")]
    return ProfileNode(
        name=str(spec["name"]),
        role=role,
        domains=domains,
        allowed_hosts=hosts,
        max_risk=risk,
        required_skills=[str(s) for s in (spec.get("required_skills") or [])],
        required_toolsets=[str(t) for t in (spec.get("required_toolsets") or [])],
        protected_domains=[],
    )


def build_team_graph(primary: str, primary_node: ProfileNode, mode: str, specialists: list[dict[str, Any]], evaluator: dict[str, Any] | None = None) -> tuple[DelegationGraph, list[Finding]]:
    if mode not in TOPOLOGY_MODES:
        raise ValueError(f"mode must be one of {TOPOLOGY_MODES}")
    findings: list[Finding] = []
    hosts = primary_node.allowed_hosts or [os.uname().nodename, "local"]
    nodes: dict[str, ProfileNode] = {primary: primary_node}
    edges: list[DelegationEdge] = []

    expected = {"single": 0, "pair": 1}.get(mode)
    if expected is not None and len(specialists) != expected:
        findings.append(Finding(
            severity="warning", scope="topology",
            message=f"mode '{mode}' expects {expected} specialist(s); got {len(specialists)}",
        ))
    if mode == "orchestrator" and evaluator is None:
        findings.append(Finding(
            severity="warning", scope="topology",
            message="orchestrator mode should include an evaluator/critic; none declared",
            recommendation="Add a reviewer specialist with read-only authority.",
        ))

    all_specs = list(specialists)
    if evaluator:
        ev = dict(evaluator)
        ev.setdefault("role", "reviewer")
        ev.setdefault("max_risk", "read-only")
        all_specs.append(ev)

    for spec in all_specs:
        name = str(spec.get("name") or "").strip()
        if not name:
            findings.append(Finding(severity="error", scope="topology", message="specialist without a name"))
            continue
        provisioning = str(spec.get("provisioning") or ("existing" if profile_dir(name).exists() else "missing"))
        exists = profile_dir(name).exists()
        if provisioning == "existing" and not exists:
            provisioning = "missing"
        if provisioning == "future-dependency":
            findings.append(Finding(
                severity="info", scope="topology",
                message=f"specialist '{name}' is declared as a future dependency; edges are drafted but inactive until it exists",
                evidence=[name],
            ))
        elif provisioning in {"create-inline", "adapt-existing"}:
            source = str(spec.get("adapt_from") or "")
            findings.append(Finding(
                severity="info", scope="topology",
                message=f"specialist '{name}' will be {'adapted from ' + source if source else 'created inline'}; primary draft is preserved while it is provisioned",
                evidence=[name] + ([source] if source else []),
            ))
        elif provisioning == "missing":
            findings.append(Finding(
                severity="warning", scope="topology",
                message=f"specialist '{name}' does not exist and has no provisioning choice",
                recommendation="Choose: create inline, adapt an existing profile, or mark as future dependency.",
                evidence=[name],
            ))
        node = _specialist_node({**spec, "name": name}, hosts)
        nodes[name] = node
        forbidden = [str(f) for f in (spec.get("forbidden") or [])]
        edges.append(DelegationEdge(
            source=primary,
            target=name,
            when=[str(w) for w in (spec.get("when") or [])] or [f"{node.domains[0]} work delegated by {primary}"],
            context_include=node.domains,
            context_exclude=list(dict.fromkeys(PROTECTED_EXCLUDES + forbidden)),
            max_runtime_seconds=int(spec.get("max_runtime_seconds") or 900),
            max_depth=1,
            max_risk=node.max_risk,
            required_return_evidence=[str(e) for e in (spec.get("required_return_evidence") or [])] or ["summary", "evidence of completed work"],
            escalation={"on_blocker": "return-to-primary"},
        ))
        if bool(spec.get("inherit_mcp")):
            findings.append(Finding(
                severity="info", scope="mcp",
                message=f"specialist '{name}' inherits MCP/tool exposure from {primary} (delegation.inherit_mcp_toolsets)",
                evidence=[name],
            ))

    graph = DelegationGraph(nodes=nodes, edges=edges)
    return graph, findings


def topology_summary(mode: str, primary: str, graph: DelegationGraph) -> dict[str, Any]:
    specialists = [n for n in graph.nodes if n != primary]
    return {
        "mode": mode,
        "primary": primary,
        "specialists": specialists,
        "edge_count": len(graph.edges),
        "tree": {primary: specialists},
    }


def annotate_change_set(cs: ProfileChangeSet, mode: str, primary: str, graph: DelegationGraph, specialists: list[dict[str, Any]]) -> None:
    cs.team_relationship_changes.append(topology_summary(mode, primary, graph))
    for spec in specialists:
        name = str(spec.get("name") or "")
        provisioning = str(spec.get("provisioning") or "existing")
        if provisioning in {"create-inline", "adapt-existing"}:
            cs.generated_files.append({
                "profile": name,
                "path": f"profiles/{name}/config.yaml",
                "kind": "specialist-provisioning-draft",
                "preview": f"# provision specialist '{name}' ({provisioning}"
                           + (f" from {spec.get('adapt_from')}" if spec.get("adapt_from") else "") + ")",
            })
