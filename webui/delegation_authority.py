"""Live profile delegation authority — the real config surface.

Hermes profile-to-profile delegation is governed by config.yaml:

    profile_delegation:
      allowed_profiles: [...]   # the authority list (who this profile may call)
      allow_self: bool
      max_depth: int
      default_timeout_seconds: int

gated by the `profile_delegation` toolset (and the separate `delegation`
toolset / `delegation:` block for spawning worker children on a model route).
This module reads and edits that authority directly — unlike the team
designer, which only produces draft plans.
"""
from __future__ import annotations

from typing import Any

from hermes_paths import backup_file, config_path, dump_yaml, load_profile_config, profiles_root, write_audit

BUILTIN_TARGETS = {"default"}


def _norm(name: str) -> str:
    return name.replace("-", "").replace("_", "").replace(" ", "").lower()


def _profile_names() -> list[str]:
    root = profiles_root()
    if not root.exists():
        return []
    return sorted((d.name for d in root.iterdir() if d.is_dir()), key=str.lower)


def _toolset_state(cfg: dict[str, Any], toolset: str) -> str:
    enabled = [str(t) for t in (cfg.get("toolsets") or [])]
    agent = cfg.get("agent") if isinstance(cfg.get("agent"), dict) else {}
    disabled = [str(t) for t in (agent.get("disabled_toolsets") or [])]
    if toolset in disabled:
        return "disabled"
    if toolset in enabled:
        return "enabled"
    platform = cfg.get("platform_toolsets") if isinstance(cfg.get("platform_toolsets"), dict) else {}
    for layer_tools in platform.values():
        if toolset in (layer_tools or []):
            return "enabled (platform layer)"
    return "not enabled"


def classify_target(target: str, names: set[str], norm_index: dict[str, str]) -> dict[str, Any]:
    if target in names or target in BUILTIN_TARGETS:
        return {"name": target, "status": "ok"}
    resolved = norm_index.get(_norm(target))
    if resolved:
        return {"name": target, "status": "stale-name", "resolves_to": resolved}
    return {"name": target, "status": "missing"}


def delegation_view(profile: str) -> dict[str, Any]:
    cfg = load_profile_config(profile)
    pd = cfg.get("profile_delegation") if isinstance(cfg.get("profile_delegation"), dict) else {}
    names = set(_profile_names())
    norm_index = {_norm(n): n for n in sorted(names)}

    targets = [classify_target(str(t), names, norm_index) for t in (pd.get("allowed_profiles") or []) if str(t).strip()]
    worker = cfg.get("delegation") if isinstance(cfg.get("delegation"), dict) else {}

    # who can delegate TO this profile (direct or via stale name)
    inbound = []
    me_norm = _norm(profile)
    for other in names:
        if other == profile:
            continue
        other_pd = load_profile_config(other).get("profile_delegation")
        if not isinstance(other_pd, dict):
            continue
        for t in other_pd.get("allowed_profiles") or []:
            if str(t) == profile:
                inbound.append({"profile": other, "declared_as": str(t), "exact": True})
                break
            if _norm(str(t)) == me_norm:
                inbound.append({"profile": other, "declared_as": str(t), "exact": False})
                break

    return {
        "profile": profile,
        "configured": bool(pd),
        "allowed_profiles": targets,
        "stale_count": sum(1 for t in targets if t["status"] == "stale-name"),
        "missing_count": sum(1 for t in targets if t["status"] == "missing"),
        "allow_self": bool(pd.get("allow_self", False)),
        "max_depth": pd.get("max_depth"),
        "default_timeout_seconds": pd.get("default_timeout_seconds"),
        "gates": {
            "profile_delegation_toolset": _toolset_state(cfg, "profile_delegation"),
            "delegation_toolset": _toolset_state(cfg, "delegation"),
        },
        "worker_route": {
            "provider": str(worker.get("provider") or ""),
            "model": str(worker.get("model") or ""),
            "orchestrator_enabled": bool(worker.get("orchestrator_enabled", False)),
            "max_spawn_depth": worker.get("max_spawn_depth"),
            "inherit_mcp_toolsets": bool(worker.get("inherit_mcp_toolsets", False)),
        },
        "inbound": inbound,
        "available_profiles": sorted(names | BUILTIN_TARGETS, key=str.lower),
        "config_key": "profile_delegation",
        "config_path": str(config_path(profile)),
    }


def set_delegation_authority(profile: str, payload: dict[str, Any], confirm: bool) -> dict[str, Any]:
    """Write profile_delegation fields with backup + audit. Targets are validated."""
    if not confirm:
        raise ValueError("confirm=true required to change delegation authority")
    cfg = load_profile_config(profile)
    cp = config_path(profile)
    if not cp.exists():
        raise FileNotFoundError(f"no config for {profile}")
    names = set(_profile_names())
    norm_index = {_norm(n): n for n in sorted(names)}

    block = cfg.setdefault("profile_delegation", {})
    if not isinstance(block, dict):
        cfg["profile_delegation"] = block = {}

    changed: dict[str, Any] = {}
    if "allowed_profiles" in payload:
        cleaned: list[str] = []
        rejected: list[str] = []
        for t in payload.get("allowed_profiles") or []:
            t = str(t).strip()
            if not t:
                continue
            info = classify_target(t, names, norm_index)
            if info["status"] == "missing":
                rejected.append(t)
            elif t not in cleaned:
                cleaned.append(t)
        if rejected:
            raise ValueError("targets do not exist (create the profile first or remove them): " + ", ".join(rejected[:8]))
        block["allowed_profiles"] = cleaned
        changed["allowed_profiles_count"] = len(cleaned)
    if "allow_self" in payload:
        block["allow_self"] = bool(payload["allow_self"])
        changed["allow_self"] = block["allow_self"]
    if "max_depth" in payload and payload["max_depth"] is not None:
        block["max_depth"] = max(1, int(payload["max_depth"]))
        changed["max_depth"] = block["max_depth"]
    if "default_timeout_seconds" in payload and payload["default_timeout_seconds"] is not None:
        block["default_timeout_seconds"] = max(1, int(payload["default_timeout_seconds"]))
        changed["default_timeout_seconds"] = block["default_timeout_seconds"]

    backup = backup_file(profile, cp, "config")
    cp.write_text(dump_yaml(cfg), encoding="utf-8")
    write_audit("set_delegation_authority", profile, {**changed, "backup": str(backup)})
    return {"ok": True, "backup": str(backup), "view": delegation_view(profile)}


def fix_stale_targets(profile: str, confirm: bool) -> dict[str, Any]:
    """Rewrite allowed_profiles entries whose names resolve fuzzily to real profiles."""
    if not confirm:
        raise ValueError("confirm=true required to rewrite delegation targets")
    view = delegation_view(profile)
    fixed = []
    new_targets = []
    for t in view["allowed_profiles"]:
        if t["status"] == "stale-name":
            fixed.append({"from": t["name"], "to": t["resolves_to"]})
            if t["resolves_to"] not in new_targets:
                new_targets.append(t["resolves_to"])
        elif t["status"] == "ok":
            if t["name"] not in new_targets:
                new_targets.append(t["name"])
        else:  # missing — keep so the human decides explicitly; report it
            new_targets.append(t["name"])
    if not fixed:
        return {"ok": True, "fixed": [], "view": view}
    cfg = load_profile_config(profile)
    cp = config_path(profile)
    block = cfg.setdefault("profile_delegation", {})
    backup = backup_file(profile, cp, "config")
    block["allowed_profiles"] = new_targets
    cp.write_text(dump_yaml(cfg), encoding="utf-8")
    write_audit("fix_stale_delegation_targets", profile, {"fixed": fixed, "backup": str(backup)})
    return {"ok": True, "backup": str(backup), "fixed": fixed, "view": delegation_view(profile)}
