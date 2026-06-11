from __future__ import annotations

from dataclasses import asdict
from typing import Any

from delegation_graph import DelegationGraph, ProfileNode, PROTECTED_DOMAINS, validate_delegation_graph
from intent_contracts import IntentContract

POWER_TOOLSETS = frozenset({"terminal", "file", "browser", "computer_use", "homeassistant", "profile_delegation"})
READ_ONLY_SAFE_TOOLSETS = frozenset({"web", "session_search", "vision", "search"})


def _finding(severity: str, scope: str, message: str, evidence: list[str] | None = None, recommendation: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "severity": severity,
        "scope": scope,
        "message": message,
        "evidence": evidence or [],
    }
    if recommendation:
        out["recommendation"] = recommendation
    return out


def _intent_required_capabilities(intent: IntentContract) -> tuple[list[str], list[str]]:
    skill_hints: list[str] = []
    toolset_hints: list[str] = []
    domain = intent.domain.lower()
    tasks = {str(t).lower() for t in intent.tasks}
    if domain in {"ui-ux", "ux", "visual-design"} or {"critique", "prototype"} & tasks:
        skill_hints.append("claude-design")
        toolset_hints.extend(["browser", "vision"])
    if intent.role == "orchestrator":
        toolset_hints.append("profile_delegation")
    if "research" in domain or "research" in tasks:
        toolset_hints.append("web")
    return list(dict.fromkeys(skill_hints)), list(dict.fromkeys(toolset_hints))


def evaluate_profile(
    profile: str,
    intent: IntentContract,
    node: ProfileNode,
    available_skills: list[str] | None = None,
    available_toolsets: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate whether a profile node fits an intent contract.

    Draft-only: this function only inspects supplied data and returns findings.
    """
    available_skills = available_skills or []
    available_toolsets = available_toolsets or []
    available_skill_set = set(available_skills)
    available_toolset_set = set(available_toolsets)

    required_skills = list(dict.fromkeys(list(node.required_skills) + _intent_required_capabilities(intent)[0]))
    required_toolsets = list(dict.fromkeys(list(node.required_toolsets) + _intent_required_capabilities(intent)[1]))

    missing_capabilities: list[str] = []
    recommended_changes: list[str] = []
    for skill in required_skills:
        if skill and skill not in available_skill_set:
            missing_capabilities.append(f"skill:{skill}")
            recommended_changes.append(f"Enable or install required skill '{skill}' for {profile}.")
    for toolset in required_toolsets:
        if toolset and toolset not in available_toolset_set:
            missing_capabilities.append(f"toolset:{toolset}")
            recommended_changes.append(f"Enable required toolset '{toolset}' for {profile}.")

    over_broad_capabilities: list[str] = []
    authority_findings: list[dict[str, Any]] = []
    max_risk = str(intent.authority_boundary.get("max_risk") or node.max_risk)
    if max_risk == "read-only":
        broad = sorted((set(node.required_toolsets) | available_toolset_set) & POWER_TOOLSETS - READ_ONLY_SAFE_TOOLSETS)
        if broad:
            msg = f"read-only profile has write-capable or high-pressure toolsets: {', '.join(broad)}"
            over_broad_capabilities.append(msg)
            authority_findings.append(_finding("warning", "authority", msg, broad, "Remove broad toolsets or raise the explicit authority boundary before apply."))

    continuity_findings: list[dict[str, Any]] = []
    delegated_domains = set(intent.authority_boundary.get("delegated_domains") or [])
    leaked_domains = sorted(delegated_domains & PROTECTED_DOMAINS)
    if leaked_domains and intent.role != "protected-continuity":
        msg = f"non-protected role would receive protected continuity domains: {', '.join(leaked_domains)}"
        continuity_findings.append(_finding("blocker", "continuity", msg, leaked_domains, "Keep continuity/project-memory/world-state with protected-continuity profiles."))
        recommended_changes.append("Remove protected domains from delegated_domains or use a protected-continuity profile.")

    host_boundary_findings: list[dict[str, Any]] = []
    if not node.allowed_hosts:
        host_boundary_findings.append(_finding("warning", "host-boundary", "profile has no allowed_hosts boundary", [], "Declare the hosts this profile may run on."))

    prompt_pressure_findings: list[dict[str, Any]] = []
    if len(intent.tasks) > 8:
        prompt_pressure_findings.append(_finding("warning", "prompt-pressure", "intent has many tasks and may create prompt pressure", intent.tasks, "Split into narrower specialist intents."))
    if len(intent.forbidden) == 0:
        prompt_pressure_findings.append(_finding("warning", "prompt-pressure", "intent has no forbidden actions", [], "Add explicit forbidden actions before apply."))

    penalty = 0
    penalty += 12 * len(missing_capabilities)
    penalty += 10 * len(over_broad_capabilities)
    penalty += 20 * len([f for f in continuity_findings if f["severity"] == "blocker"])
    penalty += 8 * len(host_boundary_findings)
    penalty += 4 * len(prompt_pressure_findings)
    fit_score = max(0, min(100, 100 - penalty))

    return {
        "profile": profile,
        "intent_profile": intent.profile,
        "fit_score": fit_score,
        "missing_capabilities": missing_capabilities,
        "over_broad_capabilities": over_broad_capabilities,
        "authority_findings": authority_findings,
        "host_boundary_findings": host_boundary_findings,
        "continuity_findings": continuity_findings,
        "prompt_pressure_findings": prompt_pressure_findings,
        "recommended_changes": recommended_changes,
    }


def validate_graph_draft(data: dict[str, Any]) -> dict[str, Any]:
    """Validate a delegation graph draft without raising to API callers."""
    findings: list[dict[str, Any]] = []
    try:
        graph = validate_delegation_graph(data)
    except Exception as exc:
        message = str(exc)
        scope = "delegation_graph"
        if "protected domain" in message or "continuity" in message or "project-memory" in message or "world-state" in message:
            scope = "continuity"
        elif "host mismatch" in message:
            scope = "host-boundary"
        elif "exceeds target node max_risk" in message or "max_risk" in message:
            scope = "authority"
        elif "not found in nodes" in message:
            scope = "graph-reference"
        findings.append(_finding("blocker", scope, message))
        return {
            "ok": False,
            "validation": [{"check": "delegation_graph", "ok": False, "message": message}],
            "findings": findings,
        }

    for edge in graph.edges:
        source = graph.nodes[edge.source]
        target = graph.nodes[edge.target]
        for domain in edge.context_include:
            if domain in PROTECTED_DOMAINS and target.role != "protected-continuity":
                findings.append(_finding("blocker", "continuity", f"protected domain '{domain}' cannot be routed to {target.role} profile '{target.name}'", [edge.source, edge.target]))
        if set(source.allowed_hosts) and set(target.allowed_hosts) and not set(source.allowed_hosts) & set(target.allowed_hosts):
            findings.append(_finding("blocker", "host-boundary", f"host mismatch for {edge.source}->{edge.target}", sorted(set(source.allowed_hosts) | set(target.allowed_hosts))))

    return {
        "ok": not any(f["severity"] == "blocker" for f in findings),
        "validation": [{"check": "delegation_graph", "ok": not findings, "message": "delegation graph draft validated" if not findings else "delegation graph has findings"}],
        "findings": findings,
        "graph": graph.to_dict(),
    }


def intent_to_dict(intent: IntentContract) -> dict[str, Any]:
    return asdict(intent)
