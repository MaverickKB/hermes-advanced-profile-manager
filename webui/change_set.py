from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, asdict
from typing import Any


def now_ts() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Finding:
    severity: str
    scope: str
    message: str
    evidence: list[str] = field(default_factory=list)
    recommendation: str | None = None


@dataclass
class ProfileChangeSet:
    id: str
    title: str
    workflow: str
    target_profiles: list[str]
    summary: str
    generated_files: list[dict[str, Any]] = field(default_factory=list)
    config_patches: list[dict[str, Any]] = field(default_factory=list)
    skill_assignments: list[dict[str, Any]] = field(default_factory=list)
    template_applications: list[dict[str, Any]] = field(default_factory=list)
    prompt_changes: list[dict[str, Any]] = field(default_factory=list)
    mcp_changes: list[dict[str, Any]] = field(default_factory=list)
    provider_changes: list[dict[str, Any]] = field(default_factory=list)
    team_relationship_changes: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    validation: list[dict[str, Any]] = field(default_factory=list)
    diff: str = ""
    backup_plan: list[dict[str, Any]] = field(default_factory=list)
    audit_preview: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=now_ts)

    # Phase A: Advanced Workbench fields
    intent_contracts: list[dict[str, Any]] = field(default_factory=list)
    delegation_edges: list[dict[str, Any]] = field(default_factory=list)
    authority_changes: list[dict[str, Any]] = field(default_factory=list)
    fit_evaluations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["findings"] = [asdict(f) if isinstance(f, Finding) else f for f in self.findings]
        return data


def new_change_set(workflow: str, title: str, target_profiles: list[str], summary: str) -> ProfileChangeSet:
    safe = "-".join([workflow, str(abs(hash((workflow, title, tuple(target_profiles), now_ts()))) % 1_000_000)])
    return ProfileChangeSet(id=safe, title=title, workflow=workflow, target_profiles=target_profiles, summary=summary)