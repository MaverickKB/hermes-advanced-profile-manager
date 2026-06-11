#!/usr/bin/env python3
"""Hermes Advanced Profile Manager WebUI.

Skill-launchable local WebUI for full-power Hermes profile configuration.
Full profile operating surface: identity + instructions + auth + env +
domains + roles + capabilities + skills + skill groups + toolsets + MCP +
providers + workers + backups + raw files, each with discover / inspect /
edit / validate / test / diff / apply / backup / rollback controls.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

WEBUI_DIR = Path(__file__).resolve().parent
if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))

import capabilities
import channels
import delegation_authority
import env_auth
import hermes_paths
import identity_files
import library_store
import mcp_providers
import skill_groups
import system_graph
import toolset_catalog
from delegation_graph import DelegationGraph, DelegationEdge, ProfileNode
from hermes_paths import (
    ROOT,
    audit_tail,
    backup_config,
    backup_file,
    config_path,
    dump_yaml,
    hermes_home,
    list_backups,
    load_profile_config,
    parse_yaml_text,
    profile_dir,
    profiles_root,
    read_text,
    utc,
    write_audit,
)
from intent_contracts import IntentContract
from profile_evaluator import validate_graph_draft
from profile_metadata import infer_profile_metadata, profile_facets
from purpose_planner import PURPOSE_LIBRARY, ROLE_DEFAULTS, plan_orchestrator_workbench, plan_profile_for_purpose
from readiness import readiness_report
from team_topology import TOPOLOGY_MODES, annotate_change_set, build_team_graph

STATIC = ROOT / "webui" / "static"
SECRET_VALUE_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password|credential|authorization)\s*[:=]\s*(['\"]?)([^\s'\"]{8,})")
SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password|credential|authorization)")


def profile_skill_roots(profile: str, config: dict[str, Any] | None = None) -> list[Path]:
    pdir = profile_dir(profile)
    cfg = config if isinstance(config, dict) else load_profile_config(profile)
    roots: list[Path] = []
    local = pdir / "skills"
    if local.exists():
        roots.append(local)
    skills_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
    raw_dirs = skills_cfg.get("external_dirs") or []
    if isinstance(raw_dirs, str):
        raw_dirs = [raw_dirs]
    if isinstance(raw_dirs, list):
        for entry in raw_dirs:
            if not str(entry).strip():
                continue
            expanded = os.path.expanduser(os.path.expandvars(str(entry)))
            path = Path(expanded)
            if not path.is_absolute():
                path = (pdir / path).resolve()
            else:
                path = path.resolve()
            if path.exists() and path not in roots:
                roots.append(path)
    return roots


def parse_skill_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    import yaml
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                return (meta if isinstance(meta, dict) else {}, parts[2])
            except Exception:
                return ({}, parts[2])
    return ({}, text)


def scan_skill_catalog(profile: str) -> dict[str, Any]:
    cfg = load_profile_config(profile)
    skills_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
    disabled = {str(x).strip() for x in (skills_cfg.get("disabled") or []) if str(x).strip()}
    roots = profile_skill_roots(profile, cfg)
    seen: set[str] = set()
    skills: list[dict[str, Any]] = []
    group_index = {g["name"]: g for g in skill_groups.list_groups()}
    group_required = {s for g in group_index.values() for s in g.get("required_skills") or []}
    group_recommended = {s for g in group_index.values() for s in g.get("recommended_skills") or []}
    for root in roots:
        for skill_md in sorted(root.rglob("SKILL.md")):
            if any(part in {".git", ".github", ".hub", ".archive", "__pycache__"} for part in skill_md.parts):
                continue
            try:
                text = skill_md.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            fm, body = parse_skill_frontmatter(text)
            name = str(fm.get("name") or skill_md.parent.name).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            desc = str(fm.get("description") or "").strip().strip('"')
            if not desc:
                for line in body.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        desc = line[:140]
                        break
            rel = str(skill_md.parent.relative_to(root)) if skill_md.parent != root else skill_md.parent.name
            category = rel.split(os.sep)[0] if os.sep in rel else "uncategorized"
            hermes_meta = ((fm.get("metadata") or {}).get("hermes") if isinstance(fm.get("metadata"), dict) else {}) or {}
            tags = []
            raw_tags = fm.get("tags") or hermes_meta.get("tags") or []
            if isinstance(raw_tags, str):
                tags = [raw_tags]
            elif isinstance(raw_tags, list):
                tags = [str(t) for t in raw_tags]
            required_toolsets = hermes_meta.get("requires_toolsets") or []
            if isinstance(required_toolsets, str):
                required_toolsets = [required_toolsets]
            enabled = name not in disabled
            why = []
            if enabled:
                why.append("direct: enabled in profile config")
            if name in group_required:
                why.append("group-required: " + ", ".join(sorted(g for g, spec in group_index.items() if name in (spec.get("required_skills") or []))))
            if name in group_recommended:
                why.append("group-recommended: " + ", ".join(sorted(g for g, spec in group_index.items() if name in (spec.get("recommended_skills") or []))))
            skills.append({
                "name": name,
                "description": desc,
                "category": category,
                "tags": tags,
                "required_toolsets": required_toolsets if isinstance(required_toolsets, list) else [],
                "path": str(skill_md.parent),
                "source_root": str(root),
                "bytes": skill_md.stat().st_size,
                "enabled": enabled,
                "status": "enabled" if enabled else "disabled",
                "why_selected": why,
            })
    skills.sort(key=lambda x: (not x["enabled"], x["category"], x["name"]))
    catalog_names = {s["name"] for s in skills}
    unknown_disabled = sorted(disabled - catalog_names)
    categories = sorted({s["category"] or "uncategorized" for s in skills})
    return {
        "profile": profile,
        "roots": [str(r) for r in roots],
        "count": len(skills),
        "enabled_count": sum(1 for s in skills if s["enabled"]),
        "disabled_count": sum(1 for s in skills if not s["enabled"]),
        "disabled": sorted(disabled),
        "unknown_disabled": unknown_disabled,
        "categories": categories,
        "skills": skills,
    }


def apply_skill_assignment(profile: str, selected: list[str], max_enabled: int | None = None) -> dict[str, Any]:
    catalog = scan_skill_catalog(profile)
    catalog_names = {s["name"] for s in catalog["skills"]}
    selected_set = {str(x).strip() for x in selected if str(x).strip()}
    unknown_selected = sorted(selected_set - catalog_names)
    if unknown_selected:
        raise ValueError("selected skills not in catalog: " + ", ".join(unknown_selected[:10]))
    if max_enabled is not None and len(selected_set) > max_enabled:
        raise ValueError(f"selected skill count {len(selected_set)} exceeds max_enabled {max_enabled}")
    cfg = load_profile_config(profile)
    skills_cfg = cfg.setdefault("skills", {})
    if not isinstance(skills_cfg, dict):
        cfg["skills"] = skills_cfg = {}
    previous_disabled = {str(x).strip() for x in (skills_cfg.get("disabled") or []) if str(x).strip()}
    # Preserve disabled entries outside the current catalog; they may refer to
    # optional/bundled skills not present on this host.
    new_disabled = (catalog_names - selected_set) | (previous_disabled - catalog_names)
    cp = config_path(profile)
    backup = backup_config(profile) if cp.exists() else None
    skills_cfg["disabled"] = sorted(new_disabled)
    cp.write_text(dump_yaml(cfg), encoding="utf-8")
    write_audit("assign_skills", profile, {
        "selected_count": len(selected_set),
        "disabled_count": len(new_disabled),
        "catalog_count": len(catalog_names),
        "backup": str(backup) if backup else None,
    })
    updated = scan_skill_catalog(profile)
    return {"ok": True, "backup": str(backup) if backup else None, "skills": updated}


def _models_endpoint(base_url: str) -> str:
    base = str(base_url or "").rstrip("/")
    if not base:
        return ""
    return base + "/models"


def poll_provider_models(provider_cfg: dict[str, Any]) -> tuple[list[str], str]:
    base_url = provider_cfg.get("base_url") if isinstance(provider_cfg, dict) else ""
    endpoint = _models_endpoint(str(base_url or ""))
    if not endpoint:
        return [], "no_base_url"
    req = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
    key_env = provider_cfg.get("key_env") or provider_cfg.get("api_key_env")
    if key_env and os.environ.get(str(key_env)):
        req.add_header("Authorization", "Bearer " + os.environ[str(key_env)])
    try:
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            raw = resp.read(2_000_000).decode("utf-8", errors="replace")
        payload = json.loads(raw)
        ids: list[str] = []
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            for item in payload["data"]:
                if isinstance(item, dict) and item.get("id"):
                    ids.append(str(item["id"]))
                elif isinstance(item, str):
                    ids.append(item)
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and item.get("id"):
                    ids.append(str(item["id"]))
                elif isinstance(item, str):
                    ids.append(item)
        return sorted(set(ids)), f"polled {endpoint}"
    except Exception as exc:
        return [], f"poll_failed: {type(exc).__name__}"


def model_catalog(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"active_provider": "", "active_model": "", "providers": []}
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    active_provider = str(model.get("provider") or "")
    active_model = str(model.get("default") or "")
    providers_cfg = data.get("providers") if isinstance(data.get("providers"), dict) else {}
    by_name: dict[str, dict[str, Any]] = {}

    def ensure(name: str) -> dict[str, Any]:
        name = str(name or "").strip()
        if not name:
            name = "custom"
        if name not in by_name:
            by_name[name] = {
                "name": name,
                "configured": False,
                "base_url": "",
                "api_mode": "",
                "default_model": "",
                "context_length": None,
                "models": [],
                "poll_status": "not_polled",
            }
        return by_name[name]

    for name, cfg in providers_cfg.items():
        entry = ensure(str(name))
        entry["configured"] = True
        if isinstance(cfg, dict):
            entry["base_url"] = str(cfg.get("base_url") or "")
            entry["api_mode"] = str(cfg.get("api_mode") or "")
            entry["default_model"] = str(cfg.get("default_model") or "")
            entry["context_length"] = cfg.get("context_length")
            polled, status = poll_provider_models(cfg)
            models = set(polled)
            if entry["default_model"]:
                models.add(entry["default_model"])
            entry["models"] = sorted(models)
            entry["poll_status"] = status

    if active_provider:
        entry = ensure(active_provider)
        if active_model and active_model not in entry["models"]:
            entry["models"] = sorted(set(entry["models"]) | {active_model})
        if active_model and not entry.get("default_model"):
            entry["default_model"] = active_model

    for fb in data.get("fallback_providers") or []:
        if isinstance(fb, dict):
            name = str(fb.get("provider") or "custom")
            entry = ensure(name)
            model_name = str(fb.get("model") or "")
            if model_name:
                entry["models"] = sorted(set(entry["models"]) | {model_name})
            if fb.get("base_url") and not entry.get("base_url"):
                entry["base_url"] = str(fb.get("base_url") or "")

    providers = sorted(by_name.values(), key=lambda x: (x["name"] != active_provider, x["name"]))
    return {"active_provider": active_provider, "active_model": active_model, "providers": providers}


def summarize_config(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    providers = data.get("providers") or {}
    mcp = data.get("mcp") or data.get("mcp_servers") or {}
    if isinstance(mcp, list):
        mcp_count = len(mcp)
    elif isinstance(mcp, dict):
        servers = mcp.get("servers") if isinstance(mcp.get("servers"), dict) else mcp
        mcp_count = len(servers) if isinstance(servers, dict) else 0
    else:
        mcp_count = 0
    toolsets = data.get("toolsets") or []
    disabled_toolsets = ((data.get("agent") or {}).get("disabled_toolsets") if isinstance(data.get("agent"), dict) else []) or []
    model = data.get("model") or {}
    return {
        "model_provider": model.get("provider") if isinstance(model, dict) else None,
        "model_default": model.get("default") if isinstance(model, dict) else None,
        "providers": sorted(providers.keys()) if isinstance(providers, dict) else [],
        "provider_count": len(providers) if isinstance(providers, dict) else 0,
        "toolsets": toolsets if isinstance(toolsets, list) else [],
        "disabled_toolsets": disabled_toolsets if isinstance(disabled_toolsets, list) else [],
        "mcp_count": mcp_count,
        "top_level_keys": sorted(data.keys()),
        "agent_keys": sorted((data.get("agent") or {}).keys()) if isinstance(data.get("agent"), dict) else [],
    }


def find_profile_skills(profile: str) -> dict[str, Any]:
    return scan_skill_catalog(profile)


def state_default_profile() -> str:
    names = hermes_paths.list_profile_names()
    if "default" in names:
        return "default"
    return names[0] if names else ""


def intent_for_profile(name: str) -> IntentContract:
    cfg = load_profile_config(name)
    summary = summarize_config(cfg)
    skills = scan_skill_catalog(name) if profile_dir(name).exists() else {"skills": []}
    metadata = infer_profile_metadata(name, summary, skills, cfg)
    role = metadata.get("role") if metadata.get("role") in {"operator", "orchestrator", "specialist", "reviewer", "worker", "fallback", "protected-continuity"} else "specialist"
    if role == "orchestrator":
        return IntentContract(
            profile=name,
            role="orchestrator",
            domain="profile-management",
            mission="Coordinate specialist profiles through bounded delegated work while preserving continuity boundaries.",
            tasks=["plan", "delegate", "review"],
            success_criteria=["specialists return required evidence", "delegation stays inside declared authority boundaries"],
            forbidden=["delegate protected continuity", "write real profiles from draft endpoints", "bypass explicit apply"],
            authority_boundary={"max_risk": "coordination", "delegated_domains": ["profile-management", "ui-ux", "coding", "research"]},
            evidence_required=["delegation log", "review findings", "validation findings"],
            confidence=0.78,
            source="inferred-orchestrator-default",
        )
    tasks = [str(t) for t in metadata.get("tasks") or [] if str(t).strip()] or ["assist"]
    risk = metadata.get("risk") if metadata.get("risk") in {"read-only", "local-write", "remote-write", "home-control", "coordination"} else "local-write"
    return IntentContract(
        profile=name,
        role=str(role),
        domain=str(metadata.get("domain") or "general"),
        mission=str(metadata.get("purpose") or f"{name} profile intent inferred from current config."),
        tasks=tasks,
        success_criteria=["return reviewable evidence", "stay inside declared authority boundary"],
        forbidden=["write real profiles from draft endpoints", "bypass explicit apply"],
        authority_boundary={"max_risk": risk, "delegated_domains": metadata.get("domains") or [metadata.get("domain") or "general"]},
        evidence_required=["summary", "validation findings"],
        confidence=0.55,
        source="inferred",
    )


def node_for_profile(name: str, role: str | None = None, domain: str | None = None) -> ProfileNode:
    cfg = load_profile_config(name)
    summary = summarize_config(cfg)
    skills = scan_skill_catalog(name) if profile_dir(name).exists() else {"skills": []}
    metadata = infer_profile_metadata(name, summary, skills, cfg)
    enabled_skills = [s["name"] for s in skills.get("skills", []) if s.get("enabled")]
    toolsets = summary.get("toolsets") or []
    node_role = role or metadata.get("role") or "specialist"
    if node_role not in {"operator", "orchestrator", "specialist", "reviewer", "worker", "fallback", "protected-continuity"}:
        node_role = "specialist"
    risk = metadata.get("risk") if metadata.get("risk") in {"read-only", "local-write", "remote-write", "home-control", "coordination"} else "local-write"
    if node_role == "orchestrator":
        risk = "coordination"
    domains = metadata.get("domains") or [domain or metadata.get("domain") or "general"]
    return ProfileNode(
        name=name,
        role=str(node_role),
        domains=[str(d) for d in domains if str(d).strip()] or [str(domain or "general")],
        allowed_hosts=[os.uname().nodename, "local"],
        max_risk=str(risk),
        required_skills=enabled_skills[:12],
        required_toolsets=[str(t) for t in toolsets if str(t).strip()],
        protected_domains=["continuity", "project-memory", "world-state"] if node_role == "protected-continuity" else [],
    )


def default_orchestrator_graph(source: str, target: str = "uxdesigner") -> DelegationGraph:
    source_node = node_for_profile(source, role="orchestrator")
    if profile_dir(target).exists():
        target_node = node_for_profile(target, role="specialist", domain="ui-ux")
        target_node.domains = list(dict.fromkeys(["ui-ux", "visual-design"] + target_node.domains))
        target_node.max_risk = "local-write"
        target_node.required_toolsets = list(dict.fromkeys(target_node.required_toolsets + ["browser", "vision", "file"]))
        target_node.required_skills = list(dict.fromkeys(target_node.required_skills + ["claude-design"]))
    else:
        target_node = ProfileNode(target, "specialist", ["ui-ux", "visual-design"], source_node.allowed_hosts, "local-write", ["claude-design"], ["browser", "vision", "file"], [])
    edge = DelegationEdge(
        source=source,
        target=target,
        when=["visual-critique", "orchestrator workbench UX review"],
        context_include=["ui-ux", "visual-design"],
        context_exclude=["continuity", "project-memory", "world-state"],
        max_runtime_seconds=900,
        max_depth=1,
        max_risk="local-write",
        required_return_evidence=["screenshot", "critique notes", "blocked-route notes if unsafe"],
        escalation={"on_blocker": "return-to-orchestrator"},
    )
    return DelegationGraph(nodes={source: source_node, target: target_node}, edges=[edge])


def profile_list() -> list[dict[str, Any]]:
    out = []
    for name in hermes_paths.list_profile_names():
        d = profile_dir(name)
        cp = config_path(name)
        exists = cp.exists()
        text = read_text(cp) if exists else ""
        data, issues = parse_yaml_text(text) if exists else ({}, [])
        summary = summarize_config(data)
        metadata = infer_profile_metadata(name, summary, {}, data if isinstance(data, dict) else {})
        out.append({
            "name": name,
            "path": str(d),
            "config_path": str(cp),
            "has_config": exists,
            "config_bytes": cp.stat().st_size if exists else 0,
            "issues": issues,
            "summary": summary,
            "metadata": metadata,
        })
    return out


def validate_config_text(text: str) -> dict[str, Any]:
    data, issues = parse_yaml_text(text)
    if data is not None and not isinstance(data, dict):
        issues.append({"severity": "error", "scope": "schema", "message": "config root must be a mapping"})
    if isinstance(data, dict):
        if "model" not in data:
            issues.append({"severity": "warning", "scope": "model", "message": "missing model section"})
        if "toolsets" in data and not isinstance(data["toolsets"], list):
            issues.append({"severity": "error", "scope": "toolsets", "message": "toolsets must be a list"})
        for match in SECRET_VALUE_RE.finditer(text):
            key = match.group(1)
            val = match.group(3)
            if key.lower().endswith(("_env", "env")):
                continue
            if not val.startswith("${") and "REDACT" not in val.upper():
                issues.append({"severity": "warning", "scope": "secrets", "message": f"possible inline secret near {key}; prefer env/secret reference"})

        def walk(obj: Any, path: str = ""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    p = f"{path}.{k}" if path else str(k)
                    key = str(k)
                    is_env_reference_key = key.lower().endswith(("_env", "env"))
                    if SECRET_KEY_RE.search(key) and not is_env_reference_key and isinstance(v, str) and v and not v.startswith("${") and not v.endswith("_ENV") and "REDACT" not in v.upper() and len(v) > 7:
                        issues.append({"severity": "warning", "scope": "secrets", "message": f"possible secret value at {p}; use env/secret reference"})
                    walk(v, p)
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    walk(v, f"{path}[{i}]")
        walk(data)
    return {"ok": not any(i["severity"] == "error" for i in issues), "issues": issues, "summary": summarize_config(data) if isinstance(data, dict) else {}}


def apply_control_patch(text: str, patch: dict[str, Any]) -> str:
    data, issues = parse_yaml_text(text)
    if issues or not isinstance(data, dict):
        raise ValueError("cannot apply controls until YAML parses as a mapping")
    if "model_provider" in patch or "model_default" in patch:
        data.setdefault("model", {})
        if patch.get("model_provider") is not None:
            data["model"]["provider"] = patch["model_provider"]
        if patch.get("model_default") is not None:
            data["model"]["default"] = patch["model_default"]
    if "toolsets" in patch:
        data["toolsets"] = patch["toolsets"]
    if "disabled_toolsets" in patch:
        data.setdefault("agent", {})
        data["agent"]["disabled_toolsets"] = patch["disabled_toolsets"]
    return dump_yaml(data)


def raw_files_view(profile: str) -> dict[str, Any]:
    cp = config_path(profile)
    identity = []
    for entry in identity_files.identity_status(profile)["files"]:
        item = dict(entry)
        if entry["active_path"] and Path(entry["active_path"]).exists():
            item["text"] = read_text(Path(entry["active_path"]))
        else:
            item["text"] = ""
        identity.append(item)
    return {
        "profile": profile,
        "config": {"path": str(cp), "exists": cp.exists(), "text": read_text(cp) if cp.exists() else ""},
        "identity": identity,
        "env": env_auth.env_status(profile),
        "auth": env_auth.auth_status(profile),
        "provenance": {
            "profile_dir": str(profile_dir(profile)),
            "hermes_home": str(hermes_home()),
            "config_path": str(cp),
            "manager_state": str(hermes_paths.STATE),
        },
    }


def export_profile_package(profile: str) -> dict[str, Any]:
    """Reviewable profile package: config + identity files. Secrets excluded by design."""
    cp = config_path(profile)
    package = {
        "format": "hermes-profile-package/v1",
        "profile": profile,
        "exported_at": utc(),
        "config_yaml": read_text(cp) if cp.exists() else "",
        "identity_files": {},
        "excluded": [".env (secrets)", "auth.json (credentials)", "caches", "sessions", "logs"],
    }
    for name in identity_files.IDENTITY_FILES:
        path = profile_dir(profile) / name
        if path.exists():
            package["identity_files"][name] = read_text(path)
    write_audit("export_profile_package", profile, {"identity_files": sorted(package["identity_files"])})
    return package


def apply_change_set(profile: str, change_set: dict[str, Any], confirm: bool) -> dict[str, Any]:
    """Bounded ChangeSet apply: skill assignments and known config patches.

    Applies exactly the sections it understands, reports everything it skipped,
    backs up first, and validates after.
    """
    if not confirm:
        raise ValueError("confirm=true required for ChangeSet apply")
    cp = config_path(profile)
    if not cp.exists():
        raise FileNotFoundError(f"no config for {profile}")
    backup = backup_config(profile)
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for assignment in change_set.get("skill_assignments") or []:
        if not isinstance(assignment, dict) or assignment.get("profile") not in (None, profile):
            skipped.append({"section": "skill_assignments", "reason": "targets another profile", "item": assignment})
            continue
        selected = assignment.get("selected") or assignment.get("recommended_enabled") or []
        if selected:
            catalog_names = {s["name"] for s in scan_skill_catalog(profile)["skills"]}
            valid = [s for s in selected if s in catalog_names]
            missing = [s for s in selected if s not in catalog_names]
            if valid:
                current = {s["name"] for s in scan_skill_catalog(profile)["skills"] if s["enabled"]}
                apply_skill_assignment(profile, sorted(current | set(valid)))
                applied.append({"section": "skill_assignments", "enabled": valid})
            if missing:
                skipped.append({"section": "skill_assignments", "reason": "skills not installed", "item": missing})

    cfg_text = read_text(config_path(profile))
    patch: dict[str, Any] = {}
    for cfg_patch in change_set.get("config_patches") or []:
        if not isinstance(cfg_patch, dict):
            continue
        path = str(cfg_patch.get("path") or "")
        if path == "/model" and isinstance(cfg_patch.get("value"), dict):
            patch["model_provider"] = cfg_patch["value"].get("provider")
            patch["model_default"] = cfg_patch["value"].get("default")
            applied.append({"section": "config_patches", "path": path})
        elif path == "/toolsets" and isinstance(cfg_patch.get("value"), list):
            patch["toolsets"] = cfg_patch["value"]
            applied.append({"section": "config_patches", "path": path})
        else:
            skipped.append({"section": "config_patches", "reason": "unsupported patch path for bounded apply", "item": path})
    if patch:
        new_text = apply_control_patch(cfg_text, patch)
        config_path(profile).write_text(new_text, encoding="utf-8")

    for section in ("prompt_changes", "mcp_changes", "provider_changes", "generated_files", "intent_contracts", "delegation_edges", "authority_changes"):
        items = change_set.get(section) or []
        if items:
            skipped.append({"section": section, "reason": "review-only section; use the dedicated control surface", "count": len(items)})

    validation = validate_config_text(read_text(config_path(profile)))
    write_audit("apply_change_set", profile, {
        "workflow": change_set.get("workflow"),
        "applied": [a["section"] for a in applied],
        "skipped": [s["section"] for s in skipped],
        "backup": str(backup),
    })
    return {"ok": True, "backup": str(backup), "applied": applied, "skipped": skipped, "validation": validation}


def rollback_last_apply(profile: str) -> dict[str, Any]:
    events = [r for r in audit_tail(500) if r.get("profile") == profile and r.get("event") in {"apply_config", "apply_change_set", "assign_skills", "set_system_prompt", "provider_upsert", "mcp_upsert_server", "set_model_route", "mcp_set_enabled"}]
    if not events:
        raise ValueError("no apply events recorded for this profile")
    last = events[-1]
    backup_path = (last.get("details") or {}).get("backup")
    if not backup_path:
        raise ValueError(f"last apply event ({last.get('event')}) recorded no backup")
    bpath = Path(backup_path)
    if not bpath.exists() or bpath.parent != hermes_paths.BACKUPS / profile:
        raise FileNotFoundError("backup file missing or outside manager backup store")
    cp = config_path(profile)
    pre = backup_config(profile) if cp.exists() else None
    shutil.copy2(bpath, cp)
    write_audit("rollback_last_apply", profile, {"restored_from": str(bpath), "undone_event": last.get("event"), "pre_rollback_backup": str(pre) if pre else None})
    return {"ok": True, "restored_from": str(bpath), "undone_event": last.get("event"), "config_text": read_text(cp)}


def compare_backup(profile: str, backup_name: str) -> dict[str, Any]:
    bdir = hermes_paths.BACKUPS / profile
    bpath = bdir / Path(backup_name).name
    if not bpath.exists() or bpath.parent != bdir:
        raise FileNotFoundError("backup not found")
    cp = config_path(profile)
    current = read_text(cp) if cp.exists() else ""
    backup_text = read_text(bpath)
    diff = "".join(difflib.unified_diff(
        backup_text.splitlines(True), current.splitlines(True),
        fromfile=f"{backup_name} (backup)", tofile=f"{profile}/config.yaml (current)",
    ))
    return {"backup": backup_name, "changed": backup_text != current, "diff": diff}


def team_plan(payload: dict[str, Any]) -> dict[str, Any]:
    primary = str(payload.get("primary") or payload.get("profile") or state_default_profile() or "default")
    mode = str(payload.get("mode") or "pair")
    if mode not in TOPOLOGY_MODES:
        raise ValueError(f"mode must be one of {TOPOLOGY_MODES}")
    specialists = [s for s in (payload.get("specialists") or []) if isinstance(s, dict)]
    evaluator = payload.get("evaluator") if isinstance(payload.get("evaluator"), dict) else None
    primary_role = "orchestrator" if mode in {"team", "orchestrator"} else ("operator" if mode == "single" else "orchestrator")
    primary_node = node_for_profile(primary, role=primary_role if mode != "single" else None)
    intent_payload = payload.get("intent") if isinstance(payload.get("intent"), dict) else None
    intent = IntentContract.from_dict(intent_payload) if intent_payload else intent_for_profile(primary)

    if mode == "single":
        graph = DelegationGraph(nodes={primary: primary_node}, edges=[])
        topology_findings = []
    else:
        graph, topology_findings = build_team_graph(primary, primary_node, mode, specialists, evaluator)

    cs = plan_orchestrator_workbench(primary, intent, graph)
    cs.workflow = f"team-topology-{mode}"
    annotate_change_set(cs, mode, primary, graph, specialists)
    cs.findings.extend(topology_findings)
    return {
        "workflow": cs.workflow,
        "mode": mode,
        "topology": {"primary": primary, "specialists": [n for n in graph.nodes if n != primary]},
        "change_set": cs.to_dict(),
        "validation": {"ok": not any(v.get("ok") is False for v in cs.validation), "checks": cs.validation},
        "findings": [f if isinstance(f, dict) else f.__dict__ for f in cs.findings],
    }


def build_profile_skill_index() -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for p in profile_list():
        try:
            catalog = scan_skill_catalog(p["name"])
            index[p["name"]] = {s["name"] for s in catalog["skills"] if s["enabled"]}
        except Exception:
            index[p["name"]] = set()
    return index


def build_profile_group_index() -> dict[str, list[str]]:
    return {p["name"]: skill_groups.enabled_groups(p["name"]) for p in profile_list()}


def profile_skill_groups_view(profile: str) -> dict[str, Any]:
    """The profile's group state: declared groups, satisfaction, available groups."""
    enabled = skill_groups.enabled_groups(profile)
    catalog = scan_skill_catalog(profile)
    catalog_names = {s["name"] for s in catalog["skills"]}
    enabled_skills = {s["name"] for s in catalog["skills"] if s["enabled"]}
    cfg = load_profile_config(profile)
    toolsets = [str(t) for t in (cfg.get("toolsets") or [])]
    groups = []
    for group in skill_groups.list_groups():
        name = group["name"]
        preview = skill_groups.group_apply_preview(name, profile, catalog_names, enabled_skills, toolsets)
        groups.append({
            **group,
            "declared_in_config": name in enabled,
            "satisfied": preview["ready"] and not preview["skills_to_enable"],
            "missing_required_skills": preview["missing_required_skills"],
            "forbidden_toolsets_present": preview["forbidden_toolsets_present"],
        })
    unknown_declared = [g for g in enabled if not any(x["name"] == g for x in groups)]
    return {
        "profile": profile,
        "enabled": enabled,
        "unknown_declared": unknown_declared,
        "groups": groups,
        "runtime": capabilities.agent_capabilities()["extensions"].get("skill_groups", {}),
        "starter_templates": sorted(skill_groups.STARTER_TEMPLATES.keys()),
        "storage": {
            "custom_dir": str(skill_groups.groups_dir()),
            "builtins_dir": str(skill_groups.builtins_dir()),
            "config_key": "skill_groups.enabled",
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesProfileManager/0.2"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (utc(), fmt % args))

    def send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, ctype: str = "text/plain; charset=utf-8", status: int = 200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> Any:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8") if n else "{}"
        return json.loads(raw or "{}")

    # ------------------------------------------------------------------- GET

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/api/state":
                profiles = profile_list()
                self.send_json({
                    "project_root": str(ROOT),
                    "hermes_home": str(hermes_home()),
                    "profiles_root": str(profiles_root()),
                    "profiles": profiles,
                    "facets": profile_facets(profiles),
                    "workflows": {
                        "domains": sorted({d["name"] for d in library_store.list_domains()} | set(PURPOSE_LIBRARY.keys())),
                        "roles": sorted({r["name"] for r in library_store.list_roles()} | set(ROLE_DEFAULTS.keys())),
                        "tasks": sorted({task for meta in profiles for task in ((meta.get("metadata") or {}).get("tasks") or [])}),
                        "topology_modes": list(TOPOLOGY_MODES),
                    },
                    "library": {
                        "domains": library_store.list_domains(),
                        "roles": library_store.list_roles(),
                        "skill_groups": skill_groups.list_groups(),
                    },
                    "audit": audit_tail(50),
                }); return
            if path == "/api/capabilities":
                refresh = query.get("refresh", ["0"])[0] in {"1", "true"}
                self.send_json(capabilities.agent_capabilities(refresh=refresh)); return
            if path == "/api/graph":
                include_skills = query.get("skills", ["1"])[0] not in {"0", "false"}
                include_toolsets = query.get("toolsets", ["0"])[0] in {"1", "true"}
                fresh = query.get("fresh", ["0"])[0] in {"1", "true"}
                if fresh:
                    system_graph._cache["graph"] = None
                self.send_json(system_graph.cached_system_graph(include_skills, include_toolsets, scan_skill_catalog)); return
            if path == "/api/library":
                self.send_json({
                    "domains": library_store.list_domains(),
                    "roles": library_store.list_roles(),
                    "skill_groups": skill_groups.list_groups(),
                    "starter_templates": sorted(skill_groups.STARTER_TEMPLATES.keys()),
                    "group_storage": {
                        "custom_dir": str(skill_groups.groups_dir()),
                        "builtins_dir": str(skill_groups.builtins_dir()),
                        "config_key": "skill_groups.enabled",
                    },
                }); return
            if path.startswith("/api/library/skill-groups/"):
                rest = path.split("/api/library/skill-groups/", 1)[1]
                parts = [urllib.parse.unquote(p) for p in rest.split("/")]
                name = parts[0]
                if len(parts) > 1 and parts[1] == "export":
                    self.send_json(skill_groups.export_group(name)); return
                self.send_json(skill_groups.get_group(name)); return
            if path.startswith("/api/profiles/"):
                rest = path.split("/", 3)[3]
                parts = [urllib.parse.unquote(p) for p in rest.split("/")]
                name = parts[0]
                action = parts[1] if len(parts) > 1 else ""
                arg = parts[2] if len(parts) > 2 else ""
                if action == "intent":
                    intent = intent_for_profile(name)
                    findings = [{"severity": "info", "scope": "draft-only", "message": "Inferred intent preview only; no profile files were written.", "evidence": [name]}]
                    self.send_json({"profile": name, "intent": intent.to_dict(), "change_set": None, "validation": {"ok": True, "issues": []}, "findings": findings}); return
                if action == "skills":
                    self.send_json(scan_skill_catalog(name)); return
                if action == "skill-groups":
                    self.send_json(profile_skill_groups_view(name)); return
                if action == "delegation":
                    view = delegation_authority.delegation_view(name)
                    view["runtime"] = capabilities.agent_capabilities()["extensions"].get("profile_delegation", {})
                    self.send_json(view); return
                if action == "channels":
                    view = channels.channels_view(name)
                    view["routing_runtime"] = capabilities.agent_capabilities()["extensions"].get("channel_profiles", {})
                    self.send_json(view); return
                if action == "models":
                    cp_tmp = config_path(name)
                    text_tmp = read_text(cp_tmp) if cp_tmp.exists() else ""
                    data_tmp, _ = parse_yaml_text(text_tmp)
                    self.send_json(model_catalog(data_tmp)); return
                if action == "identity":
                    if arg:
                        self.send_json(identity_files.read_identity_file(name, arg)); return
                    self.send_json(identity_files.identity_status(name)); return
                if action == "env":
                    self.send_json(env_auth.env_status(name)); return
                if action == "auth":
                    self.send_json(env_auth.auth_status(name)); return
                if action == "toolsets":
                    refresh = query.get("refresh", ["0"])[0] in {"1", "true"}
                    self.send_json(toolset_catalog.toolset_inventory(name, refresh=refresh)); return
                if action == "mcp":
                    self.send_json(mcp_providers.mcp_inventory(name)); return
                if action == "providers":
                    self.send_json(mcp_providers.provider_inventory(name)); return
                if action == "readiness":
                    live = query.get("live", ["1"])[0] not in {"0", "false"}
                    self.send_json(readiness_report(name, live=live)); return
                if action == "raw":
                    self.send_json(raw_files_view(name)); return
                if action == "export":
                    self.send_json(export_profile_package(name)); return
                if action == "backups":
                    self.send_json({"profile": name, "backups": list_backups(name)}); return
                cp = config_path(name)
                if not cp.exists():
                    self.send_json({"error": "profile config not found"}, 404); return
                text = read_text(cp)
                validation = validate_config_text(text)
                skill_payload = find_profile_skills(name)
                summary = validation.get("summary") or {}
                self.send_json({
                    "name": name,
                    "profile_dir": str(profile_dir(name)),
                    "config_path": str(cp),
                    "config_text": text,
                    "validation": validation,
                    "metadata": infer_profile_metadata(name, summary, skill_payload, parse_yaml_text(text)[0] if isinstance(parse_yaml_text(text)[0], dict) else {}),
                    "skills": skill_payload,
                    "model_catalog": model_catalog(parse_yaml_text(text)[0]),
                    "backups": list_backups(name),
                    "audit": [r for r in audit_tail(100) if r.get("profile") == name],
                }); return
            # static
            if path == "/":
                target = STATIC / "index.html"
            else:
                rel = Path(urllib.parse.unquote(path.lstrip("/")))
                if rel.is_absolute() or ".." in rel.parts:
                    self.send_json({"error": "bad path"}, 400); return
                target = STATIC / rel
            if target.exists() and target.is_file():
                ctype = "text/html; charset=utf-8" if target.suffix == ".html" else "text/css; charset=utf-8" if target.suffix == ".css" else "application/javascript; charset=utf-8" if target.suffix == ".js" else "text/plain; charset=utf-8"
                self.send_text(read_text(target), ctype); return
            self.send_json({"error": "not found"}, 404)
        except (KeyError, FileNotFoundError) as exc:
            self.send_json({"error": str(exc)}, 404)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    # ------------------------------------------------------------------ POST

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            payload = self.read_body()
            confirm = bool(payload.get("confirm"))
            if path == "/api/shutdown":
                if not confirm:
                    self.send_json({"error": "confirm=true required to shut down"}, 400); return
                write_audit("server_shutdown", "-", {"via": "api"})
                self.send_json({"ok": True, "message": "Profile Manager shutting down."})
                import threading
                threading.Thread(target=lambda: (time.sleep(0.3), _request_shutdown()), daemon=True).start()
                return
            if path == "/api/graphs/validate":
                validation = validate_graph_draft(payload.get("graph") if isinstance(payload.get("graph"), dict) else payload)
                self.send_json({"change_set": None, "validation": validation, "findings": validation.get("findings", [])}); return
            if path == "/api/workflows/orchestrator-plan":
                source = str(payload.get("profile") or payload.get("source") or state_default_profile() or "default")
                target = str(payload.get("target") or payload.get("target_profile") or "uxdesigner")
                intent_payload = payload.get("intent") if isinstance(payload.get("intent"), dict) else None
                intent = IntentContract.from_dict(intent_payload) if intent_payload else intent_for_profile(source)
                graph_payload = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
                graph = DelegationGraph.from_dict(graph_payload) if graph_payload else default_orchestrator_graph(source, target)
                cs = plan_orchestrator_workbench(source, intent, graph)
                self.send_json({"workflow": cs.workflow, "change_set": cs.to_dict(), "validation": {"ok": not any(v.get("ok") is False for v in cs.validation), "checks": cs.validation}, "findings": [f if isinstance(f, dict) else f.__dict__ for f in cs.findings]}); return
            if path == "/api/workflows/team-plan":
                self.send_json(team_plan(payload)); return
            if path == "/api/workflows/purpose-plan":
                target = str(payload.get("target_profile") or payload.get("target") or state_default_profile())
                skill_payload = scan_skill_catalog(target) if target else {"skills": []}
                self.send_json(plan_profile_for_purpose(payload, profile_list(), skill_payload)); return
            if path == "/api/library/domains":
                if payload.get("delete"):
                    self.send_json(library_store.delete_domain(str(payload.get("name")))); return
                self.send_json(library_store.upsert_domain(str(payload.get("name")), payload)); return
            if path == "/api/library/roles":
                if payload.get("delete"):
                    self.send_json(library_store.delete_role(str(payload.get("name")))); return
                self.send_json(library_store.upsert_role(str(payload.get("name")), payload)); return
            if path == "/api/library/skill-groups":
                if payload.get("delete"):
                    self.send_json(skill_groups.delete_group(str(payload.get("name")))); return
                if payload.get("duplicate_from"):
                    self.send_json(skill_groups.duplicate_group(str(payload["duplicate_from"]), str(payload.get("name")))); return
                if payload.get("from_template"):
                    self.send_json(skill_groups.create_from_template(str(payload["from_template"]), payload.get("name"))); return
                if payload.get("import_manifest"):
                    manifest = payload["import_manifest"]
                    if isinstance(manifest, dict) and isinstance(manifest.get("group"), dict):
                        manifest = manifest["group"]
                    self.send_json(skill_groups.import_group(manifest)); return
                self.send_json(skill_groups.upsert_group(str(payload.get("name")), payload)); return
            if path.startswith("/api/library/skill-groups/"):
                rest = path.split("/api/library/skill-groups/", 1)[1]
                parts = [urllib.parse.unquote(p) for p in rest.split("/")]
                group = parts[0]
                sub = parts[1] if len(parts) > 1 else ""
                if sub == "preview":
                    profile = str(payload.get("profile") or "")
                    catalog = scan_skill_catalog(profile)
                    cfg = load_profile_config(profile)
                    self.send_json(skill_groups.group_apply_preview(
                        group, profile,
                        {s["name"] for s in catalog["skills"]},
                        {s["name"] for s in catalog["skills"] if s["enabled"]},
                        [str(t) for t in (cfg.get("toolsets") or [])],
                    )); return
                if sub == "profiles":
                    self.send_json({"group": group, "profiles": skill_groups.profiles_using_group(group, build_profile_skill_index(), build_profile_group_index())}); return
                self.send_json({"error": "not found"}, 404); return
            if path.startswith("/api/profiles/") and path != "/api/profiles":
                rest = path.split("/", 3)[3]
                parts = [urllib.parse.unquote(p) for p in rest.split("/")]
                name = parts[0]
                action = parts[1] if len(parts) > 1 else ""
                arg = parts[2] if len(parts) > 2 else ""
                sub = parts[3] if len(parts) > 3 else ""
                if action == "intent-plan":
                    intent_payload = payload.get("intent") if isinstance(payload.get("intent"), dict) else None
                    intent = IntentContract.from_dict(intent_payload) if intent_payload else intent_for_profile(name)
                    graph_payload = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
                    graph = DelegationGraph.from_dict(graph_payload) if graph_payload else default_orchestrator_graph(name, str(payload.get("target") or "uxdesigner"))
                    cs = plan_orchestrator_workbench(name, intent, graph)
                    self.send_json({"workflow": cs.workflow, "change_set": cs.to_dict(), "validation": {"ok": not any(v.get("ok") is False for v in cs.validation), "checks": cs.validation}, "findings": [f if isinstance(f, dict) else f.__dict__ for f in cs.findings]}); return
                if action == "skills":
                    self.send_json(scan_skill_catalog(name)); return
                if action == "validate":
                    self.send_json(validate_config_text(payload.get("config_text", ""))); return
                if action == "controls":
                    text = payload.get("config_text", "")
                    new_text = apply_control_patch(text, payload.get("patch") or {})
                    self.send_json({"config_text": new_text, "validation": validate_config_text(new_text)}); return
                if action == "diff":
                    cp = config_path(name)
                    old = read_text(cp) if cp.exists() else ""
                    new = payload.get("config_text", "")
                    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=f"{name}/config.yaml (current)", tofile=f"{name}/config.yaml (draft)"))
                    self.send_json({"diff": diff, "changed": old != new}); return
                if action == "apply":
                    cp = config_path(name)
                    new = payload.get("config_text", "")
                    validation = validate_config_text(new)
                    if not confirm:
                        self.send_json({"error": "confirm=true required for writes", "validation": validation}, 400); return
                    if not validation["ok"]:
                        self.send_json({"error": "validation failed", "validation": validation}, 400); return
                    cp.parent.mkdir(parents=True, exist_ok=True)
                    backup = backup_config(name) if cp.exists() else None
                    cp.write_text(new, encoding="utf-8")
                    write_audit("apply_config", name, {"config_path": str(cp), "backup": str(backup) if backup else None, "bytes": len(new.encode('utf-8'))})
                    self.send_json({"ok": True, "backup": str(backup) if backup else None, "validation": validation, "backups": list_backups(name)}); return
                if action == "skill-groups":
                    if sub == "enable":
                        self.send_json(skill_groups.set_group_enabled(name, arg, bool(payload.get("enabled", True)), confirm)); return
                    self.send_json({"error": "unknown skill-groups action"}, 404); return
                if action == "delegation":
                    if arg == "fix-stale":
                        self.send_json(delegation_authority.fix_stale_targets(name, confirm)); return
                    self.send_json(delegation_authority.set_delegation_authority(name, payload, confirm)); return
                if action == "channels":
                    if sub == "routing":
                        self.send_json(channels.set_routing(name, arg, payload.get("ops") or [], confirm)); return
                    self.send_json(channels.set_platform_block(name, arg, str(payload.get("block_yaml") or ""), confirm)); return
                if action == "assign-skills":
                    selected = payload.get("selected") or []
                    max_enabled = payload.get("max_enabled")
                    if max_enabled is not None:
                        max_enabled = int(max_enabled)
                    self.send_json(apply_skill_assignment(name, selected, max_enabled)); return
                if action == "apply-changeset":
                    cs = payload.get("change_set")
                    if not isinstance(cs, dict):
                        self.send_json({"error": "change_set object required"}, 400); return
                    self.send_json(apply_change_set(name, cs, confirm)); return
                if action == "identity":
                    if not arg:
                        self.send_json({"error": "identity file name required"}, 400); return
                    if payload.get("copy_from"):
                        self.send_json(identity_files.copy_identity_file(name, arg, str(payload["copy_from"]), confirm)); return
                    self.send_json(identity_files.write_identity_file(name, arg, str(payload.get("text") or ""), confirm)); return
                if action == "system-prompt":
                    self.send_json(identity_files.set_system_prompt(name, str(payload.get("text") or ""), confirm)); return
                if action == "env":
                    if arg == "copy":
                        self.send_json(env_auth.env_copy(name, str(payload.get("source") or "global"), confirm)); return
                    if arg == "reveal":
                        self.send_json(env_auth.env_reveal(name, str(payload.get("key") or ""))); return
                    self.send_json(env_auth.env_apply(name, payload.get("ops") or [], confirm)); return
                if action == "auth":
                    if arg == "copy":
                        self.send_json(env_auth.auth_copy(name, str(payload.get("source") or "default"), confirm)); return
                    if arg == "use-default":
                        self.send_json(env_auth.auth_use_default(name, confirm)); return
                    if arg == "remove-provider":
                        self.send_json(env_auth.auth_remove_provider(name, str(payload.get("provider") or ""), confirm)); return
                    self.send_json({"error": "unknown auth action"}, 404); return
                if action == "mcp":
                    if sub == "test" or arg == "test":
                        server = arg if sub == "test" else str(payload.get("server") or "")
                        self.send_json(mcp_providers.mcp_test(name, server)); return
                    if sub == "enable" or arg == "enable":
                        server = arg if sub == "enable" else str(payload.get("server") or "")
                        self.send_json(mcp_providers.mcp_set_enabled(name, server, bool(payload.get("enabled", True)), confirm)); return
                    server = arg or str(payload.get("server") or "")
                    self.send_json(mcp_providers.mcp_upsert_server(name, server, payload.get("spec") or payload, confirm)); return
                if action == "providers":
                    if sub == "test-auth":
                        self.send_json(mcp_providers.provider_test_auth(name, arg)); return
                    if sub == "test-completion":
                        self.send_json(mcp_providers.provider_test_completion(name, arg, str(payload.get("model") or ""))); return
                    provider = arg or str(payload.get("provider") or "")
                    self.send_json(mcp_providers.provider_upsert(name, provider, payload.get("spec") or payload, confirm)); return
                if action == "model-route":
                    self.send_json(mcp_providers.set_model_route(name, str(payload.get("route") or "primary"), str(payload.get("provider") or ""), str(payload.get("model") or ""), confirm)); return
                if action == "toolsets" and arg == "partial-plan":
                    self.send_json(toolset_catalog.partial_application_plan(name, str(payload.get("toolset") or ""), payload.get("wanted_tools") or [])); return
                if action == "backup":
                    backup = backup_config(name)
                    write_audit("create_backup", name, {"backup": str(backup)})
                    self.send_json({"ok": True, "backup": str(backup), "backups": list_backups(name)}); return
                if action == "backups" and arg == "compare":
                    self.send_json(compare_backup(name, str(payload.get("backup") or ""))); return
                if action == "rollback-last-apply":
                    if not confirm:
                        self.send_json({"error": "confirm=true required for rollback"}, 400); return
                    self.send_json(rollback_last_apply(name)); return
                if action == "rollback":
                    backup_name = payload.get("backup")
                    if not backup_name:
                        self.send_json({"error": "backup required"}, 400); return
                    bdir = hermes_paths.BACKUPS / name
                    bpath = (bdir / Path(backup_name).name)
                    if not bpath.exists() or bpath.parent != bdir:
                        self.send_json({"error": "backup not found"}, 404); return
                    cp = config_path(name)
                    current_backup = backup_config(name) if cp.exists() else None
                    shutil.copy2(bpath, cp)
                    write_audit("rollback_config", name, {"restored_from": str(bpath), "pre_rollback_backup": str(current_backup) if current_backup else None})
                    self.send_json({"ok": True, "config_text": read_text(cp), "backups": list_backups(name)}); return
            if path == "/api/profiles":
                name = payload.get("name", "").strip()
                base = payload.get("base", "").strip()
                if not re.match(r"^[A-Za-z0-9_. -]{1,80}$", name):
                    self.send_json({"error": "invalid profile name"}, 400); return
                d = profile_dir(name)
                if d.exists():
                    self.send_json({"error": "profile already exists"}, 400); return
                d.mkdir(parents=True)
                if base:
                    src = config_path(base)
                    if src.exists():
                        shutil.copy2(src, d / "config.yaml")
                    else:
                        (d / "config.yaml").write_text("model:\n  provider: ''\n  default: ''\ntoolsets: []\n", encoding="utf-8")
                else:
                    (d / "config.yaml").write_text("model:\n  provider: ''\n  default: ''\ntoolsets: []\n", encoding="utf-8")
                write_audit("create_profile", name, {"base": base or None, "path": str(d)})
                self.send_json({"ok": True, "profile": name, "profiles": profile_list()}); return
            self.send_json({"error": "not found"}, 404)
        except (KeyError, FileNotFoundError) as exc:
            self.send_json({"error": str(exc)}, 404)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)


_httpd: ThreadingHTTPServer | None = None
_server_port: int | None = None


def _request_shutdown() -> None:
    if _server_port is not None:
        try:
            (hermes_paths.STATE / f"server-{_server_port}.pid").unlink(missing_ok=True)
        except Exception:
            pass
    if _httpd is not None:
        _httpd.shutdown()


def main(argv=None):
    global _httpd, _server_port
    ap = argparse.ArgumentParser(description="Launch Hermes Advanced Profile Manager WebUI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5194)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--hermes-home", default="", help="Explicit Hermes installation root (overrides HERMES_HOME resolution; useful in profile-scoped sessions)")
    ns = ap.parse_args(argv)
    if ns.hermes_home:
        os.environ["PROFILE_MANAGER_HERMES_HOME"] = str(Path(ns.hermes_home).expanduser())
    _server_port = ns.port
    if not hermes_paths.list_profile_names():
        print(json.dumps({
            "warning": "no Hermes profiles found at resolved home (no profiles/ directory and no root config.yaml)",
            "resolved_hermes_home": str(hermes_home()),
            "hint": "pass --hermes-home /path/to/.hermes or set HERMES_HOME/PROFILE_MANAGER_HERMES_HOME",
        }, indent=2), file=sys.stderr, flush=True)
    hermes_paths.STATE.mkdir(parents=True, exist_ok=True)
    url = f"http://{ns.host}:{ns.port}/"
    print(json.dumps({"url": url, "project_root": str(ROOT), "hermes_home": str(hermes_home()), "profiles_root": str(profiles_root())}, indent=2), flush=True)
    if not ns.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    _httpd = ThreadingHTTPServer((ns.host, ns.port), Handler)
    try:
        _httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _httpd.server_close()


if __name__ == "__main__":
    main()
