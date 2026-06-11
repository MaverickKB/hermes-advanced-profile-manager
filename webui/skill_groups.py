"""Hermes-native skill group manifests.

Storage layout:

    built-ins:     <hermes-agent>/hermes_cli/profile_groups/builtins/*.yaml
    custom:        <HERMES_HOME>/skill_groups/*.yaml
    profile ref:   config.yaml -> skill_groups.enabled[]
    applied state: <HERMES_HOME>/state/profile_group_state.json (read-only here)

Manifests are YAML capability bundles: purpose, risk,
required/recommended skills, toolset requirements, MCP dependencies, prompt
policy, diagnostics, repairs, export rules, conflicts, delegation routes.
This manager reads and writes the canonical locations so Hermes tooling and
the WebUI always see the same group data. Secret values never belong in
manifests; export defaults to excluding runtime state.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import yaml

from hermes_paths import (
    backup_file,
    config_path,
    dump_yaml,
    hermes_home,
    load_profile_config,
    read_text,
    write_audit,
)

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
RISK_LEVELS = ("low", "medium", "high", "critical")

# Built-in group names, offered as starter templates until
# hermes-agent ships its own builtins directory.
STARTER_TEMPLATES: dict[str, dict[str, Any]] = {
    "hermes-operator": {
        "title": "Hermes Operator",
        "description": "Configure, troubleshoot, and repair Hermes profiles, tools, gateway, MCP, and skills.",
        "risk_level": "high",
        "required_skills": ["hermes-agent", "systematic-debugging"],
        "recommended_skills": ["plan"],
        "required_toolsets": ["terminal", "file", "skills"],
        "recommended_toolsets": ["session_search", "delegation"],
    },
    "local-dev": {
        "title": "Local Development",
        "description": "Repo-grounded coding, debugging, and testing on the local host.",
        "risk_level": "medium",
        "required_skills": ["systematic-debugging"],
        "recommended_skills": ["plan", "test-driven-development"],
        "required_toolsets": ["terminal", "file"],
        "recommended_toolsets": ["session_search", "web"],
    },
    "gateway-admin": {
        "title": "Gateway Admin",
        "description": "Operate and administer Hermes gateway platforms and channels.",
        "risk_level": "critical",
        "required_toolsets": ["terminal", "file"],
        "forbidden_toolsets": ["homeassistant"],
        "recommended_skills": ["hermes-agent"],
    },
    "macos-automation": {
        "title": "macOS Automation",
        "description": "Automate macOS-local applications and workflows.",
        "risk_level": "high",
        "required_toolsets": ["terminal", "file"],
        "recommended_toolsets": ["browser", "vision"],
    },
}

FLAT_DEFAULTS: dict[str, Any] = {
    "name": "",
    "title": "",
    "description": "",
    "version": 1,
    "risk_level": "medium",
    "required_skills": [],
    "recommended_skills": [],
    "forbidden_skills": [],
    "required_toolsets": [],
    "recommended_toolsets": [],
    "forbidden_toolsets": [],
    "mcp_dependencies": [],
    "mcp_optional": [],
    "prompt_policy": {},
    "platforms": {},
    "diagnostics": [],
    "allowed_repairs": [],
    "dry_run_required": True,
    "exportable": True,
    "conflicts": [],
    "delegation_routes": [],
}


def groups_dir() -> Path:
    return hermes_home() / "skill_groups"


def builtins_dir() -> Path:
    return hermes_home() / "hermes-agent" / "hermes_cli" / "profile_groups" / "builtins"


def group_state_path() -> Path:
    return hermes_home() / "state" / "profile_group_state.json"


def _validate_name(name: str) -> str:
    name = str(name or "").strip().lower()
    if not NAME_RE.match(name):
        raise ValueError("group id must be lowercase alphanumeric with . _ - (max 80 chars)")
    return name


def _ts() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------- manifest translation

def manifest_to_flat(manifest: dict[str, Any], name: str = "") -> dict[str, Any]:
    """Nested manifest shape -> flat API shape."""
    skills = manifest.get("skills") if isinstance(manifest.get("skills"), dict) else {}
    toolsets = manifest.get("toolsets") if isinstance(manifest.get("toolsets"), dict) else {}
    mcp = manifest.get("mcp_servers") if isinstance(manifest.get("mcp_servers"), dict) else {}
    repairs = manifest.get("repairs") if isinstance(manifest.get("repairs"), dict) else {}
    export = manifest.get("export") if isinstance(manifest.get("export"), dict) else {}

    def _list(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        return [str(x) for x in value or [] if str(x).strip()]

    flat = dict(FLAT_DEFAULTS)
    flat.update({
        "name": str(manifest.get("id") or name),
        "title": str(manifest.get("title") or ""),
        "description": str(manifest.get("description") or manifest.get("purpose") or ""),
        "version": int(manifest.get("version") or 1),
        "risk_level": str(manifest.get("risk_level") or "medium"),
        "required_skills": _list(skills.get("required") or manifest.get("required_skills")),
        "recommended_skills": _list(skills.get("recommended") or manifest.get("recommended_skills")),
        "forbidden_skills": _list(skills.get("forbidden") or manifest.get("forbidden_skills")),
        "required_toolsets": _list(toolsets.get("required") or manifest.get("required_toolsets")),
        "recommended_toolsets": _list(toolsets.get("recommended") or manifest.get("recommended_toolsets")),
        "forbidden_toolsets": _list(toolsets.get("forbidden") or manifest.get("forbidden_toolsets")),
        "mcp_dependencies": _list(mcp.get("required") or manifest.get("mcp_dependencies")),
        "mcp_optional": _list(mcp.get("optional") or manifest.get("mcp_optional")),
        "prompt_policy": manifest.get("prompt_policy") if isinstance(manifest.get("prompt_policy"), dict) else {},
        "platforms": manifest.get("platforms") if isinstance(manifest.get("platforms"), dict) else {},
        "diagnostics": list(manifest.get("diagnostics") or []),
        "allowed_repairs": _list(repairs.get("allowed") or manifest.get("allowed_repairs")),
        "dry_run_required": bool(repairs.get("dry_run_required", manifest.get("dry_run_required", True))),
        "exportable": bool(export.get("exportable", manifest.get("exportable", True))),
        "conflicts": _list(manifest.get("conflicts")),
        "delegation_routes": list(manifest.get("delegation") or manifest.get("delegation_routes") or []),
        "updated_at": str(manifest.get("updated_at") or ""),
    })
    if flat["risk_level"] not in RISK_LEVELS:
        flat["risk_level"] = "medium"
    return flat


def flat_to_manifest(flat: dict[str, Any]) -> dict[str, Any]:
    """Flat API shape -> nested manifest shape (what we persist)."""
    return {
        "id": flat["name"],
        "title": flat.get("title") or flat["name"],
        "description": flat.get("description") or "",
        "version": int(flat.get("version") or 1),
        "risk_level": flat.get("risk_level") or "medium",
        "skills": {
            "required": flat.get("required_skills") or [],
            "recommended": flat.get("recommended_skills") or [],
            "forbidden": flat.get("forbidden_skills") or [],
        },
        "toolsets": {
            "required": flat.get("required_toolsets") or [],
            "recommended": flat.get("recommended_toolsets") or [],
            "forbidden": flat.get("forbidden_toolsets") or [],
        },
        "mcp_servers": {
            "required": flat.get("mcp_dependencies") or [],
            "optional": flat.get("mcp_optional") or [],
        },
        "prompt_policy": flat.get("prompt_policy") or {},
        "platforms": flat.get("platforms") or {},
        "diagnostics": flat.get("diagnostics") or [],
        "repairs": {
            "allowed": flat.get("allowed_repairs") or [],
            "dry_run_required": bool(flat.get("dry_run_required", True)),
        },
        "export": {"exportable": bool(flat.get("exportable", True))},
        "conflicts": flat.get("conflicts") or [],
        "delegation": flat.get("delegation_routes") or [],
        "updated_at": flat.get("updated_at") or _ts(),
    }


# -------------------------------------------------------------- store reads

def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(read_text(path))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def list_groups() -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    bdir = builtins_dir()
    if bdir.is_dir():
        for path in sorted(bdir.glob("*.yaml")):
            manifest = _read_manifest(path)
            if manifest:
                flat = manifest_to_flat(manifest, path.stem)
                flat["source"] = "hermes-builtin"
                flat["path"] = str(path)
                out[flat["name"]] = flat
    gdir = groups_dir()
    if gdir.is_dir():
        for path in sorted(gdir.glob("*.yaml")):
            manifest = _read_manifest(path)
            if manifest:
                flat = manifest_to_flat(manifest, path.stem)
                flat["source"] = "custom" if flat["name"] not in out else "custom-override"
                flat["path"] = str(path)
                out[flat["name"]] = flat
    return sorted(out.values(), key=lambda g: g["name"])


def get_group(name: str) -> dict[str, Any]:
    for group in list_groups():
        if group["name"] == name:
            return group
    raise KeyError(f"skill group not found: {name}")


def applied_state() -> dict[str, Any]:
    path = group_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(read_text(path))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ------------------------------------------------------------- store writes

def upsert_group(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = _validate_name(name)
    existing: dict[str, Any] | None = None
    try:
        existing = get_group(name)
    except KeyError:
        pass
    if existing and existing.get("source") == "hermes-builtin":
        # Customizing a builtin writes a HERMES_HOME override, never the repo file.
        pass
    flat = dict(FLAT_DEFAULTS)
    if existing:
        flat.update({k: existing.get(k, v) for k, v in FLAT_DEFAULTS.items()})
    flat["name"] = name
    for key in FLAT_DEFAULTS:
        if key in payload and key != "name":
            flat[key] = payload[key]
    if "title" in payload:
        flat["title"] = str(payload["title"] or "")
    flat["version"] = int(existing.get("version", 0) if existing else 0) + 1
    flat["updated_at"] = _ts()
    if flat["risk_level"] not in RISK_LEVELS:
        raise ValueError(f"risk_level must be one of {RISK_LEVELS}")

    gdir = groups_dir()
    gdir.mkdir(parents=True, exist_ok=True)
    path = gdir / f"{name}.yaml"
    path.write_text(dump_yaml(flat_to_manifest(flat)), encoding="utf-8")
    write_audit("upsert_skill_group", "-", {"group": name, "version": flat["version"], "path": str(path)})
    return {"ok": True, "group": get_group(name)}


def delete_group(name: str) -> dict[str, Any]:
    path = groups_dir() / f"{name}.yaml"
    if not path.exists():
        try:
            source = get_group(name).get("source")
        except KeyError:
            raise KeyError(f"skill group not found: {name}")
        raise ValueError(f"cannot delete {source} group {name}; only HERMES_HOME/skill_groups manifests are deletable here")
    path.unlink()
    write_audit("delete_skill_group", "-", {"group": name, "path": str(path)})
    return {"ok": True, "groups": list_groups()}


def duplicate_group(source: str, new_name: str) -> dict[str, Any]:
    src = get_group(source)
    new_name = _validate_name(new_name)
    if any(g["name"] == new_name for g in list_groups()):
        raise ValueError(f"skill group already exists: {new_name}")
    payload = {k: v for k, v in src.items() if k in FLAT_DEFAULTS and k != "name"}
    payload["version"] = 0
    payload["description"] = f"Adapted from {source}. {payload.get('description', '')}".strip()
    return upsert_group(new_name, payload)


def create_from_template(template: str, name: str | None = None) -> dict[str, Any]:
    if template not in STARTER_TEMPLATES:
        raise KeyError(f"unknown starter template: {template}")
    target = _validate_name(name or template)
    if any(g["name"] == target for g in list_groups()):
        raise ValueError(f"skill group already exists: {target}")
    return upsert_group(target, dict(STARTER_TEMPLATES[template]))


def import_group(manifest: dict[str, Any]) -> dict[str, Any]:
    if isinstance(manifest.get("group"), dict):
        manifest = manifest["group"]
    flat = manifest_to_flat(manifest) if ("skills" in manifest or "id" in manifest) else {**FLAT_DEFAULTS, **manifest}
    name = _validate_name(str(flat.get("name") or manifest.get("name") or ""))
    flat["version"] = 0
    return upsert_group(name, flat)


def export_group(name: str) -> dict[str, Any]:
    group = get_group(name)
    if not group.get("exportable", True):
        raise ValueError(f"skill group {name} is marked not exportable")
    manifest = flat_to_manifest(group)
    return {
        "format": "hermes-skill-group-manifest/v1",
        "exported_at": _ts(),
        "manifest_yaml": dump_yaml(manifest),
        "group": manifest,
    }


# -------------------------------------------------- profile <-> group wiring

def enabled_groups(profile: str) -> list[str]:
    cfg = load_profile_config(profile)
    block = cfg.get("skill_groups") if isinstance(cfg.get("skill_groups"), dict) else {}
    return [str(g) for g in (block.get("enabled") or []) if str(g).strip()]


def set_group_enabled(profile: str, group: str, enabled: bool, confirm: bool) -> dict[str, Any]:
    """Write the config.yaml skill_groups.enabled[] reference with backup."""
    if not confirm:
        raise ValueError("confirm=true required to change profile skill groups")
    get_group(group)  # must exist
    cfg = load_profile_config(profile)
    cp = config_path(profile)
    if not cp.exists():
        raise FileNotFoundError(f"no config for {profile}")
    block = cfg.setdefault("skill_groups", {})
    if not isinstance(block, dict):
        cfg["skill_groups"] = block = {}
    current = [str(g) for g in (block.get("enabled") or []) if str(g).strip()]
    if enabled and group not in current:
        current.append(group)
    if not enabled and group in current:
        current.remove(group)
    backup = backup_file(profile, cp, "config")
    block["enabled"] = current
    cp.write_text(dump_yaml(cfg), encoding="utf-8")
    write_audit("set_skill_group_enabled", profile, {"group": group, "enabled": enabled, "backup": str(backup)})
    return {"ok": True, "backup": str(backup), "enabled": current}


def profiles_using_group(group_name: str, profile_skill_index: dict[str, set[str]], profile_enabled_index: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    """Profiles that declare this group (config reference) or satisfy its required skills."""
    group = get_group(group_name)
    required = set(group.get("required_skills") or [])
    enabled_index = profile_enabled_index or {}
    out = []
    for profile in sorted(set(profile_skill_index) | set(enabled_index)):
        enabled_skills = profile_skill_index.get(profile, set())
        declared = group_name in (enabled_index.get(profile) or [])
        present = required & enabled_skills
        if not declared and not present:
            continue
        out.append({
            "profile": profile,
            "declared": declared,
            "satisfies": bool(required) and present == required,
            "present": sorted(present),
            "missing": sorted(required - enabled_skills),
        })
    return out


def group_apply_preview(group_name: str, profile: str, catalog_names: set[str], enabled_names: set[str], toolsets: list[str]) -> dict[str, Any]:
    """Exact changes applying a group to a profile would make — preview only."""
    group = get_group(group_name)
    required = list(group.get("required_skills") or [])
    recommended = list(group.get("recommended_skills") or [])
    forbidden = set(group.get("forbidden_skills") or [])
    to_enable = [s for s in required + recommended if s in catalog_names and s not in enabled_names]
    to_disable = sorted(forbidden & enabled_names)
    missing = [s for s in required if s not in catalog_names]
    current_toolsets = set(toolsets or [])
    toolsets_to_add = [t for t in group.get("required_toolsets") or [] if t not in current_toolsets]
    toolsets_forbidden = sorted(set(group.get("forbidden_toolsets") or []) & current_toolsets)
    declared = group_name in enabled_groups(profile)
    return {
        "group": group_name,
        "profile": profile,
        "declared_in_config": declared,
        "skills_to_enable": to_enable,
        "skills_to_disable": to_disable,
        "missing_required_skills": missing,
        "toolsets_to_add": toolsets_to_add,
        "forbidden_toolsets_present": toolsets_forbidden,
        "mcp_dependencies": group.get("mcp_dependencies") or [],
        "dry_run_required": bool(group.get("dry_run_required", True)),
        "risk_level": group.get("risk_level"),
        "conflicts": group.get("conflicts") or [],
        "ready": not missing and not toolsets_forbidden,
    }
