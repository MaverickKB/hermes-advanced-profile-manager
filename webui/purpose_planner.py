from __future__ import annotations

import json
from typing import Any

from change_set import Finding, ProfileChangeSet, new_change_set
from delegation_graph import DelegationGraph
from intent_contracts import IntentContract
from profile_evaluator import evaluate_profile, validate_graph_draft

PURPOSE_LIBRARY = {
    "coding": {
        "skills": ["systematic-debugging", "plan"],
        "toolsets": ["terminal", "file", "session_search"],
        "mcp": [],
        "prompt_sections": ["Mission", "Repo grounding", "Testing and commit discipline"],
    },
    "ui-ux": {
        "skills": ["claude-design", "design-md"],
        "toolsets": ["browser", "vision", "file"],
        "mcp": [],
        "prompt_sections": ["Visual quality bar", "Interaction rules", "Browser verification"],
    },
    "research": {
        "skills": ["plan"],
        "toolsets": ["web", "browser", "file"],
        "mcp": [],
        "prompt_sections": ["Source quality", "Bounded batches", "Synthesis"],
    },
    "devops": {
        "skills": ["systematic-debugging", "plan"],
        "toolsets": ["terminal", "file", "web"],
        "mcp": [],
        "prompt_sections": ["Host boundaries", "Rollback plan", "Control-plane safety"],
    },
    "profile-management": {
        "skills": ["hermes-agent", "systematic-debugging"],
        "toolsets": ["terminal", "file", "browser", "profile_delegation", "session_search"],
        "mcp": [],
        "prompt_sections": ["Profile purpose", "Skill routing", "Safe apply", "Continuity"],
    },
    "memory-continuity": {
        "skills": ["aethermind-continuity"],
        "toolsets": ["session_search", "memory", "file"],
        "mcp": [],
        "prompt_sections": ["Continuity contract", "AetherMind usage", "Session handoff"],
    },
}

ROLE_DEFAULTS = {
    "operator": {"risk": "local-write", "review": "self-review with diff"},
    "orchestrator": {"risk": "coordination", "review": "requires manager/reviewer graph"},
    "reviewer": {"risk": "read-only", "review": "no direct writes by default"},
    "specialist": {"risk": "bounded-write", "review": "domain-scoped writes"},
    "worker": {"risk": "bounded-write", "review": "manager-approved writes"},
}


def _catalog_lookup(skill_catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s.get("name"): s for s in skill_catalog.get("skills", []) if s.get("name")}


def plan_profile_for_purpose(payload: dict[str, Any], profiles: list[dict[str, Any]], skill_catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    domain = str(payload.get("domain") or "profile-management")
    role = str(payload.get("role") or "specialist")
    tasks = [str(x) for x in payload.get("tasks") or [] if str(x).strip()]
    target = str(payload.get("target_profile") or "new-profile")
    name = str(payload.get("new_profile_name") or target or "new-profile")
    risk = str(payload.get("risk") or ROLE_DEFAULTS.get(role, {}).get("risk") or "local-write")
    library = PURPOSE_LIBRARY.get(domain, PURPOSE_LIBRARY["profile-management"])
    catalog = _catalog_lookup(skill_catalog or {})
    recommended_skills = list(dict.fromkeys(library["skills"] + [s for s in payload.get("extra_skills") or [] if s]))
    present = [s for s in recommended_skills if s in catalog]
    missing = [s for s in recommended_skills if s not in catalog]
    toolsets = list(dict.fromkeys(library["toolsets"] + [t for t in payload.get("toolsets") or [] if t]))
    title = f"Build {role} profile for {domain}"
    article = "an" if role[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
    summary = f"Generate {article} {role} profile plan for {domain} work with tasks: {', '.join(tasks) or 'general assistance'}."
    cs = new_change_set("build-profile-for-purpose", title, [target], summary)
    cs.config_patches.append({
        "op": "merge",
        "path": "/profile_metadata",
        "value": {"domain": domain, "role": role, "tasks": tasks, "risk": risk, "purpose": summary},
    })
    cs.skill_assignments.append({"profile": target, "recommended_enabled": present, "missing": missing})
    cs.provider_changes.append({"profile": target, "note": "Use selected provider/model from Model & toolsets workflow; no invented default."})
    cs.prompt_changes.append({
        "profile": target,
        "source": "SOUL.md or system prompt",
        "recommended_sections": library["prompt_sections"],
    })
    for mcp in library["mcp"]:
        cs.mcp_changes.append({"profile": target, "server": mcp, "action": "verify-or-add"})
    cs.generated_files.append({
        "path": f"profiles/{name}/SOUL.md",
        "kind": "identity-draft",
        "preview": f"# {name}\n\nRole: {role}\nDomain: {domain}\nTasks: {', '.join(tasks) or 'general'}\n\n## Operating posture\n- Use selected skills and tools for this profile's purpose.\n- Keep changes behind validation/diff/apply.\n",
    })
    cs.backup_plan.append({"profile": target, "action": "backup config.yaml before any write"})
    cs.audit_preview.append({"event": "plan_profile_for_purpose", "profile": target, "domain": domain, "role": role})
    if missing:
        cs.findings.append(Finding(
            severity="warning",
            scope="skills",
            message=f"{len(missing)} recommended skills were not found in this profile's catalog.",
            evidence=missing,
            recommendation="Install/adapt missing skills or choose an available equivalent before applying template.",
        ))
    cs.findings.append(Finding(
        severity="info",
        scope="workflow",
        message="This is a generated plan, not a direct write. Review, validate, diff, then apply through the shared safe-apply path.",
    ))
    return {
        "request": {"domain": domain, "role": role, "tasks": tasks, "target_profile": target, "risk": risk},
        "recommended": {
            "skills": recommended_skills,
            "present_skills": present,
            "missing_skills": missing,
            "toolsets": toolsets,
            "mcp": library["mcp"],
            "prompt_sections": library["prompt_sections"],
        },
        "change_set": cs.to_dict(),
    }


def _profile_targets(profile: str, graph: DelegationGraph) -> list[str]:
    names = [profile]
    for edge in graph.edges:
        if edge.source == profile and edge.target not in names:
            names.append(edge.target)
        if edge.target == profile and edge.source not in names:
            names.append(edge.source)
    for name in graph.nodes:
        if name not in names:
            names.append(name)
    return names


def _node_intent(node_name: str, intent: IntentContract, graph: DelegationGraph) -> IntentContract:
    if node_name == intent.profile:
        return intent
    node = graph.nodes[node_name]
    return IntentContract(
        profile=node.name,
        role=node.role,
        domain=node.domains[0] if node.domains else "general",
        mission=f"Perform bounded {', '.join(node.domains[:2]) or 'general'} work delegated by {intent.profile}.",
        tasks=list(dict.fromkeys([cond for edge in graph.edges if edge.target == node.name for cond in edge.when])) or ["assist"],
        success_criteria=["return required evidence to orchestrator"],
        forbidden=["own protected continuity", "write real profiles from draft endpoints"],
        authority_boundary={"max_risk": node.max_risk, "delegated_domains": node.domains},
        evidence_required=list(dict.fromkeys([ev for edge in graph.edges if edge.target == node.name for ev in edge.required_return_evidence])) or ["summary"],
        confidence=0.75,
        source="inferred",
    )


def plan_orchestrator_workbench(profile: str, intent: IntentContract, graph: DelegationGraph) -> ProfileChangeSet:
    """Build a draft-only ChangeSet for an orchestrator delegation workbench plan."""
    targets = _profile_targets(profile, graph)
    cs = new_change_set(
        "orchestrator-delegation-intent",
        f"Draft orchestrator workbench plan for {profile}",
        targets,
        f"Draft intent contracts and delegation graph for {profile}; review only, no live profile mutation.",
    )

    intent_contracts = [_node_intent(name, intent, graph).to_dict() for name in targets if name in graph.nodes]
    cs.intent_contracts.extend(intent_contracts)
    cs.delegation_edges.extend([edge.__dict__.copy() for edge in graph.edges])

    graph_validation = validate_graph_draft(graph.to_dict())
    cs.validation.extend(graph_validation.get("validation", []))
    for finding in graph_validation.get("findings", []):
        cs.findings.append(Finding(
            severity=finding.get("severity", "warning"),
            scope=finding.get("scope", "delegation_graph"),
            message=finding.get("message", "delegation graph finding"),
            evidence=finding.get("evidence", []),
            recommendation=finding.get("recommendation"),
        ))

    for name in targets:
        node = graph.nodes.get(name)
        if not node:
            continue
        node_intent = _node_intent(name, intent, graph)
        fit = evaluate_profile(name, node_intent, node, available_skills=node.required_skills, available_toolsets=node.required_toolsets)
        cs.fit_evaluations.append(fit)
        cs.skill_assignments.append({
            "profile": name,
            "recommended_enabled": node.required_skills,
            "missing": [],
            "source": "delegation graph required_skills",
        })
        cs.config_patches.append({
            "profile": name,
            "op": "merge-preview",
            "path": "/orchestrator_workbench",
            "value": {
                "role": node.role,
                "domains": node.domains,
                "allowed_hosts": node.allowed_hosts,
                "max_risk": node.max_risk,
                "required_toolsets": node.required_toolsets,
            },
        })
        cs.prompt_changes.append({
            "profile": name,
            "source": "SOUL.md or system prompt",
            "recommended_sections": [
                "Intent contract",
                "Delegation boundaries",
                "Required return evidence",
                "Draft-only profile mutation rule",
            ],
        })
        cs.backup_plan.append({"profile": name, "action": "backup config.yaml and sidecars before any explicit apply"})
        cs.audit_preview.append({"event": "draft_orchestrator_workbench_plan", "profile": name, "workflow": "orchestrator-delegation-intent"})

    cs.generated_files.append({
        "profile": profile,
        "path": f"profiles/{profile}/intent.contracts.preview.json",
        "kind": "intent-sidecar-preview",
        "preview": json.dumps({"intent_contracts": cs.intent_contracts}, indent=2, sort_keys=True),
    })
    cs.generated_files.append({
        "profile": profile,
        "path": f"profiles/{profile}/delegation.graph.preview.json",
        "kind": "delegation-graph-sidecar-preview",
        "preview": json.dumps({"delegation_edges": cs.delegation_edges, "nodes": graph.to_dict()["nodes"]}, indent=2, sort_keys=True),
    })
    cs.authority_changes.extend([
        {
            "profile": name,
            "max_risk": graph.nodes[name].max_risk,
            "allowed_hosts": graph.nodes[name].allowed_hosts,
            "source": "delegation graph draft",
        }
        for name in targets
        if name in graph.nodes
    ])
    cs.findings.append(Finding(
        severity="info",
        scope="draft-only",
        message="Orchestrator workbench plan is draft-only; it writes no real profile files unless routed through explicit apply.",
        recommendation="Review validation, diff, backup plan, and audit preview before apply.",
    ))
    return cs
