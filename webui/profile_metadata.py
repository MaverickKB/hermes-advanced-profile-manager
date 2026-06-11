from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

DOMAIN_KEYWORDS = {
    "coding": ["code", "coding", "software", "debug", "repo", "git", "test", "python", "typescript", "rust"],
    "devops": ["deploy", "docker", "ssh", "server", "service", "monitor", "grafana", "prometheus", "kubernetes"],
    "research": ["research", "search", "web", "paper", "source", "synthesis"],
    "writing": ["write", "writer", "draft", "prose", "edit", "narrative"],
    "ui-ux": ["ui", "ux", "visual", "design", "layout", "browser", "mockup"],
    "home-automation": ["home", "assistant", "ha", "kiosk", "automation", "world", "sonos"],
    "memory-continuity": ["memory", "continuity", "aethermind", "honcho", "recall", "journal"],
    "profile-management": ["profile", "hermes", "skill", "mcp", "config", "manager"],
    "review": ["review", "critic", "critique", "audit", "verify"],
}

ROLE_KEYWORDS = {
    "orchestrator": ["orchestrator", "manager", "coordinate", "delegat", "route"],
    "reviewer": ["review", "critic", "verify", "audit"],
    "specialist": ["specialist", "designer", "research", "writer", "devops", "operator"],
    "worker": ["worker", "agent", "builder", "executor"],
    "operator": ["operator", "admin", "profile"],
}

RISK_TOOLSETS = {
    "remote-write": {"terminal", "file", "ssh", "devops"},
    "home-control": {"homeassistant", "world_state"},
    "browser-action": {"browser", "computer_use"},
}


def _tokens(*parts: Any) -> str:
    blob = " ".join(str(p or "") for p in parts)
    return re.sub(r"[^a-z0-9_-]+", " ", blob.lower())


def _score_keywords(blob: str, table: dict[str, list[str]]) -> list[tuple[str, int]]:
    scored = []
    for key, words in table.items():
        score = sum(1 for word in words if word in blob)
        if score:
            scored.append((key, score))
    return sorted(scored, key=lambda x: (-x[1], x[0]))


def infer_profile_metadata(profile: str, summary: dict[str, Any], skills: dict[str, Any] | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    skills = skills or {}
    config = config or {}
    enabled_skills = [s for s in skills.get("skills", []) if s.get("enabled")]
    skill_blob = " ".join(
        " ".join(str(x or "") for x in [s.get("name"), s.get("category"), s.get("description"), " ".join(s.get("tags") or [])])
        for s in enabled_skills
    )
    cfg_blob = _tokens(profile, summary.get("model_provider"), summary.get("model_default"), summary.get("toolsets"), summary.get("providers"), summary.get("top_level_keys"), skill_blob)
    domains = [k for k, _ in _score_keywords(cfg_blob, DOMAIN_KEYWORDS)[:4]] or ["general"]
    role_scores = _score_keywords(cfg_blob, ROLE_KEYWORDS)
    role = role_scores[0][0] if role_scores else "specialist"
    toolsets = set(summary.get("toolsets") or [])
    risk = "read-only"
    for label, markers in RISK_TOOLSETS.items():
        if toolsets & markers:
            risk = label
            break
    tasks = []
    for domain in domains:
        if domain == "coding": tasks += ["build", "debug", "review"]
        elif domain == "devops": tasks += ["deploy", "monitor", "repair"]
        elif domain == "research": tasks += ["research", "synthesize"]
        elif domain == "ui-ux": tasks += ["critique", "prototype"]
        elif domain == "profile-management": tasks += ["configure", "evaluate", "orchestrate"]
        elif domain == "memory-continuity": tasks += ["orient", "record", "repair"]
        elif domain == "home-automation": tasks += ["observe", "diagnose", "control"]
        elif domain == "writing": tasks += ["draft", "edit"]
        elif domain == "review": tasks += ["review", "verify"]
    tasks = sorted(dict.fromkeys(tasks))[:8] or ["assist"]
    purpose = f"{role} profile for {', '.join(domains[:3])} work: {', '.join(tasks[:4])}."
    return {
        "profile": profile,
        "domain": domains[0],
        "domains": domains,
        "tasks": tasks,
        "role": role,
        "risk": risk,
        "purpose": purpose,
        "tags": sorted(set(domains + tasks + [role, risk])),
        "source": "inferred",
    }


def profile_facets(profiles: list[dict[str, Any]]) -> dict[str, list[str]]:
    facets: dict[str, set[str]] = {"domains": set(), "tasks": set(), "roles": set(), "risks": set()}
    for p in profiles:
        meta = p.get("metadata") or {}
        for d in meta.get("domains") or [meta.get("domain")]:
            if d: facets["domains"].add(str(d))
        for t in meta.get("tasks") or []:
            facets["tasks"].add(str(t))
        if meta.get("role"): facets["roles"].add(str(meta["role"]))
        if meta.get("risk"): facets["risks"].add(str(meta["risk"]))
    return {k: sorted(v) for k, v in facets.items()}
