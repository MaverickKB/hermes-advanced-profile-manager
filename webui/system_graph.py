"""Whole-system profile graph for the visual Explorer.

Assembles every profile, its real cross-profile wiring, and its shared
resources into one typed graph with per-profile health signals, so a human can
see what 50+ profiles are doing, delegating to, and where stale or broken
configuration hides.

Edge sources are real config surfaces only:
  profile_delegation.allowed_profiles  -> profile-to-profile delegation
  discord.channel_profiles             -> channel routing between profiles
  model / fallback_providers /
  delegation / auxiliary               -> provider routes
  mcp_servers                          -> MCP dependencies
  skill_groups.enabled                 -> declared skill groups
  skills (enabled catalog)             -> skill usage (optional layer)
  toolsets                             -> toolset usage (optional layer)
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any

import skill_groups as sg
from env_auth import auth_status
from hermes_paths import list_profile_names, config_path, load_profile_config, parse_yaml_text, profile_dir, profiles_root, read_text

STALE_CONFIG_DAYS = 90

_cache: dict[str, Any] = {"ts": 0.0, "key": None, "graph": None}
CACHE_TTL_SECONDS = 20


def _norm(name: str) -> str:
    return name.replace("-", "").replace("_", "").replace(" ", "").lower()


def _profile_names() -> list[str]:
    return list_profile_names()


def _provider_routes(cfg: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(provider, model, route_kind) tuples from every model route surface."""
    routes: list[tuple[str, str, str]] = []
    model = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    if model.get("provider"):
        routes.append((str(model["provider"]), str(model.get("default") or ""), "primary"))
    for fb in cfg.get("fallback_providers") or []:
        if isinstance(fb, dict) and fb.get("provider"):
            routes.append((str(fb["provider"]), str(fb.get("model") or ""), "fallback"))
    delegation = cfg.get("delegation") if isinstance(cfg.get("delegation"), dict) else {}
    if delegation.get("provider"):
        routes.append((str(delegation["provider"]), str(delegation.get("model") or ""), "worker-model"))
    auxiliary = cfg.get("auxiliary") if isinstance(cfg.get("auxiliary"), dict) else {}
    for aux_name, aux in auxiliary.items():
        if isinstance(aux, dict) and aux.get("provider"):
            routes.append((str(aux["provider"]), str(aux.get("model") or ""), f"auxiliary:{aux_name}"))
    return routes


def _mcp_servers(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("mcp_servers", "mcp"):
        block = cfg.get(key)
        if isinstance(block, dict):
            servers = block.get("servers") if isinstance(block.get("servers"), dict) else block
            if isinstance(servers, dict):
                out = []
                for name, server in servers.items():
                    if isinstance(server, dict):
                        enabled_raw = server.get("enabled", True)
                        out.append({
                            "name": str(name),
                            "enabled": str(enabled_raw).strip().lower() not in {"false", "0", "no", "off"},
                        })
                return out
    return []


def build_system_graph(include_skills: bool = True, include_toolsets: bool = False, scan_skills_fn=None) -> dict[str, Any]:
    """Build the full typed graph. scan_skills_fn(profile)->catalog injected by server."""
    names = _profile_names()
    # "default" is Hermes' built-in home profile (the hermes home itself),
    # a legitimate routing/delegation target even though it has no
    # profiles/<name> directory.
    name_set = set(names) | {"default"}
    norm_index: dict[str, list[str]] = {}
    for n in names:
        norm_index.setdefault(_norm(n), []).append(n)

    group_names = {g["name"] for g in sg.list_groups()}
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    now = dt.datetime.now(dt.timezone.utc)

    def node(node_id: str, kind: str, label: str, **extra) -> dict[str, Any]:
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, "kind": kind, "label": label, **extra}
        return nodes[node_id]

    def edge(src: str, dst: str, kind: str, **extra) -> None:
        edges.append({"source": src, "target": dst, "kind": kind, **extra})

    profile_meta: dict[str, dict[str, Any]] = {}

    for name in names:
        pid = f"profile:{name}"
        cp = config_path(name)
        health_reasons: list[str] = []
        level = "ok"

        def worse(new_level: str) -> None:
            nonlocal level
            order = {"ok": 0, "warn": 1, "error": 2}
            if order[new_level] > order[level]:
                level = new_level

        cfg: dict[str, Any] = {}
        if not cp.exists():
            health_reasons.append("no config.yaml")
            worse("error")
        else:
            text = read_text(cp)
            data, issues = parse_yaml_text(text)
            if issues:
                health_reasons.append("config.yaml does not parse")
                worse("error")
            elif isinstance(data, dict):
                cfg = data
            age_days = (now - dt.datetime.fromtimestamp(cp.stat().st_mtime, dt.timezone.utc)).days
            if age_days > STALE_CONFIG_DAYS:
                health_reasons.append(f"config untouched for {age_days} days")
                worse("warn")

        model = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
        if cp.exists() and not (model.get("provider") and model.get("default")):
            health_reasons.append("no primary model route")
            worse("warn")

        # auth staleness (file metadata only, no network)
        try:
            auth = auth_status(name)
            if auth["source"] == "missing":
                health_reasons.append("no auth source")
                worse("warn")
            elif auth.get("stale"):
                health_reasons.append("auth.json stale")
                worse("warn")
        except Exception:
            pass

        # skills
        skill_names_enabled: list[str] = []
        skills_count = 0
        if scan_skills_fn is not None and cp.exists():
            try:
                catalog = scan_skills_fn(name)
                skills_count = catalog.get("count", 0)
                skill_names_enabled = [s["name"] for s in catalog.get("skills", []) if s.get("enabled")]
                if skills_count and not skill_names_enabled:
                    health_reasons.append("all installed skills disabled")
                    worse("warn")
            except Exception:
                pass

        # alias duplicates
        twins = [t for t in norm_index.get(_norm(name), []) if t != name]
        if twins:
            health_reasons.append("alias/duplicate name: " + ", ".join(twins))
            worse("warn")

        # declared skill groups
        declared = sg.enabled_groups(name) if cp.exists() else []
        for group in declared:
            gid = f"group:{group}"
            if group in group_names:
                node(gid, "group", group)
                edge(pid, gid, "group")
            else:
                node(gid, "group", group, missing=True)
                edge(pid, gid, "group", broken=True)
                health_reasons.append(f"declared skill group '{group}' has no manifest")
                worse("error")

        # delegation targets
        pd = cfg.get("profile_delegation") if isinstance(cfg.get("profile_delegation"), dict) else {}
        delegates = [str(t) for t in (pd.get("allowed_profiles") or []) if str(t).strip()]
        broken_targets = []
        for target in delegates:
            if target in name_set:
                edge(pid, f"profile:{target}", "delegates")
            else:
                resolved = norm_index.get(_norm(target), [])
                if resolved:
                    edge(pid, f"profile:{resolved[0]}", "delegates", declared_as=target, fuzzy=True)
                    broken_targets.append(f"{target} (exists as {resolved[0]})")
                else:
                    broken_targets.append(target)
        if broken_targets:
            health_reasons.append("delegation targets not found: " + ", ".join(broken_targets[:6]))
            worse("error")

        # channel routing
        discord = cfg.get("discord") if isinstance(cfg.get("discord"), dict) else {}
        channel_profiles = discord.get("channel_profiles") if isinstance(discord.get("channel_profiles"), dict) else {}
        routed: dict[str, int] = {}
        for _channel, target in channel_profiles.items():
            target = str(target)
            if target != name:
                routed[target] = routed.get(target, 0) + 1
        for target, count in routed.items():
            if target in name_set:
                edge(pid, f"profile:{target}", "routes", channels=count)
            else:
                health_reasons.append(f"channel routing to unknown profile '{target}'")
                worse("error")

        # provider routes
        for provider, model_name, route in _provider_routes(cfg):
            prov_id = f"provider:{provider}"
            node(prov_id, "provider", provider)
            edge(pid, prov_id, "model-route", route=route, model=model_name)

        # MCP servers
        for server in _mcp_servers(cfg):
            mid = f"mcp:{server['name']}"
            node(mid, "mcp", server["name"])
            edge(pid, mid, "mcp", enabled=server["enabled"])

        # skills layer
        if include_skills:
            for skill in skill_names_enabled:
                sid = f"skill:{skill}"
                node(sid, "skill", skill)
                edge(pid, sid, "skill")

        # toolsets layer
        if include_toolsets:
            for toolset in cfg.get("toolsets") or []:
                tid = f"toolset:{toolset}"
                node(tid, "toolset", str(toolset))
                edge(pid, tid, "toolset")

        meta = {
            "health": level,
            "health_reasons": health_reasons,
            "provider": str(model.get("provider") or ""),
            "model": str(model.get("default") or ""),
            "skills_enabled": len(skill_names_enabled),
            "skills_installed": skills_count,
            "delegates_out": len(delegates),
            "groups": declared,
            "config_path": str(cp),
        }
        profile_meta[name] = meta
        node(pid, "profile", name, **meta)

    if "profile:default" in {e["target"] for e in edges} and "profile:default" not in nodes:
        node("profile:default", "profile", "default", health="ok", health_reasons=[],
             provider="", model="", skills_enabled=0, skills_installed=0, delegates_out=0,
             groups=[], config_path=str(profiles_root().parent / "config.yaml"), builtin=True)

    health_counts = {"ok": 0, "warn": 0, "error": 0}
    for name, meta in profile_meta.items():
        health_counts[meta["health"]] += 1

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {
            "profiles": len(names),
            "nodes": len(nodes),
            "edges": len(edges),
            "health": health_counts,
        },
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def cached_system_graph(include_skills: bool, include_toolsets: bool, scan_skills_fn) -> dict[str, Any]:
    key = (include_skills, include_toolsets)
    if _cache["graph"] is not None and _cache["key"] == key and time.time() - _cache["ts"] < CACHE_TTL_SECONDS:
        return _cache["graph"]
    graph = build_system_graph(include_skills, include_toolsets, scan_skills_fn)
    _cache.update({"ts": time.time(), "key": key, "graph": graph})
    return graph
