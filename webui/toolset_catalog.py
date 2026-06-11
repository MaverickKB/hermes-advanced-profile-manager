"""Toolset and tool inspection.

The real tool→toolset registry is extracted from the installed hermes-agent
(model_tools.TOOL_TO_TOOLSET_MAP) and cached; a static snapshot is the
fallback when extraction is unavailable. Every toolset is inspectable down to
its tools with risk classification and which config layer enables it.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

import hermes_paths
from hermes_paths import hermes_home, load_profile_config


def _registry_cache():
    return hermes_paths.STATE / "toolset-registry.json"

# Snapshot of hermes-agent model_tools registry (fallback when live extraction fails).
STATIC_REGISTRY: dict[str, list[str]] = {
    "browser": ["browser_back", "browser_click", "browser_console", "browser_get_images", "browser_navigate", "browser_press", "browser_scroll", "browser_snapshot", "browser_type", "browser_vision"],
    "browser-cdp": ["browser_cdp", "browser_dialog"],
    "clarify": ["clarify"],
    "code_execution": ["execute_code"],
    "computer_use": ["computer_use"],
    "cronjob": ["cronjob"],
    "delegation": ["delegate_task"],
    "discord": ["discord"],
    "discord_admin": ["discord_admin"],
    "file": ["patch", "read_file", "search_files", "write_file"],
    "homeassistant": ["ha_call_service", "ha_get_state", "ha_list_entities", "ha_list_services"],
    "image_gen": ["image_generate"],
    "kanban": ["kanban_block", "kanban_comment", "kanban_complete", "kanban_create", "kanban_heartbeat", "kanban_link", "kanban_list", "kanban_show", "kanban_unblock"],
    "memory": ["memory"],
    "messaging": ["send_message"],
    "moa": ["mixture_of_agents"],
    "profile_delegation": ["delegate_profile"],
    "session_search": ["session_search"],
    "skills": ["skill_manage", "skill_view", "skills_list"],
    "spotify": ["spotify_albums", "spotify_devices", "spotify_library", "spotify_playback", "spotify_playlists", "spotify_queue", "spotify_search"],
    "terminal": ["process", "read_terminal", "terminal"],
    "todo": ["todo"],
    "tts": ["text_to_speech"],
    "video": ["video_analyze"],
    "video_gen": ["video_generate"],
    "vision": ["vision_analyze"],
    "web": ["web_extract", "web_search"],
    "x_search": ["x_search"],
}

TOOL_RISK: dict[str, str] = {
    # explicit per-tool overrides; default falls back to toolset risk
    "read_file": "read-only", "search_files": "read-only", "read_terminal": "read-only",
    "browser_snapshot": "read-only", "browser_console": "read-only", "browser_get_images": "read-only",
    "ha_get_state": "read-only", "ha_list_entities": "read-only", "ha_list_services": "read-only",
    "ha_call_service": "home-control",
    "web_search": "read-only", "web_extract": "read-only", "session_search": "read-only",
    "skills_list": "read-only", "skill_view": "read-only",
    "kanban_list": "read-only", "kanban_show": "read-only",
}

TOOLSET_RISK: dict[str, str] = {
    "terminal": "host-execute", "code_execution": "host-execute", "computer_use": "host-execute",
    "file": "local-write", "browser": "browser-action", "browser-cdp": "browser-action",
    "homeassistant": "home-control", "messaging": "external-write", "discord": "external-write",
    "discord_admin": "external-write", "tts": "local-write", "image_gen": "external-call",
    "video_gen": "external-call", "delegation": "coordination", "profile_delegation": "coordination",
    "moa": "external-call", "web": "read-only", "vision": "external-call", "video": "external-call",
    "memory": "local-write", "kanban": "local-write", "todo": "local-write", "cronjob": "local-write",
    "skills": "local-write", "session_search": "read-only", "clarify": "read-only",
    "spotify": "external-write", "x_search": "read-only",
}

EXTRACT_SNIPPET = (
    "import json\n"
    "from model_tools import TOOL_TO_TOOLSET_MAP\n"
    "ts = {}\n"
    "for tool, t in TOOL_TO_TOOLSET_MAP.items():\n"
    "    ts.setdefault(t, []).append(tool)\n"
    "print(json.dumps({k: sorted(v) for k, v in ts.items()}))\n"
)


def extract_live_registry(timeout: float = 30.0) -> dict[str, list[str]] | None:
    agent_dir = hermes_home() / "hermes-agent"
    python = agent_dir / "venv" / "bin" / "python"
    if not python.exists():
        return None
    try:
        proc = subprocess.run(
            [str(python), "-c", EXTRACT_SNIPPET],
            cwd=str(agent_dir), capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            return None
        line = proc.stdout.strip().splitlines()[-1]
        data = json.loads(line)
        if isinstance(data, dict) and data:
            return {str(k): [str(x) for x in v] for k, v in data.items()}
    except Exception:
        return None
    return None


def toolset_registry(refresh: bool = False) -> dict[str, Any]:
    cache = _registry_cache()
    if not refresh and cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(cached.get("registry"), dict) and cached["registry"]:
                return cached
        except Exception:
            pass
    live = extract_live_registry()
    payload = {
        "source": "hermes-agent model_tools registry" if live else "static snapshot (live extraction unavailable)",
        "registry": live or STATIC_REGISTRY,
    }
    try:
        hermes_paths.STATE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass
    return payload


def tool_entry(toolset: str, tool: str) -> dict[str, Any]:
    return {
        "name": tool,
        "toolset": toolset,
        "risk": TOOL_RISK.get(tool, TOOLSET_RISK.get(toolset, "unknown")),
        "source": "hermes-agent native toolset",
    }


def toolset_inventory(profile: str, refresh: bool = False) -> dict[str, Any]:
    """Resolve every known toolset against the profile's config layers."""
    cfg = load_profile_config(profile)
    reg = toolset_registry(refresh=refresh)
    registry: dict[str, list[str]] = reg["registry"]
    enabled = [str(t) for t in (cfg.get("toolsets") or []) if str(t).strip()]
    agent = cfg.get("agent") if isinstance(cfg.get("agent"), dict) else {}
    disabled = [str(t) for t in (agent.get("disabled_toolsets") or []) if str(t).strip()]
    platform = cfg.get("platform_toolsets") if isinstance(cfg.get("platform_toolsets"), dict) else {}
    platform_layers = {layer: [str(t) for t in (tools or [])] for layer, tools in platform.items()}

    names = sorted(set(registry) | set(enabled) | set(disabled))
    toolsets = []
    for name in names:
        tools = [tool_entry(name, t) for t in registry.get(name, [])]
        enabled_by = []
        if name in enabled:
            enabled_by.append("profile toolsets list")
        for layer, layer_tools in platform_layers.items():
            if name in layer_tools:
                enabled_by.append(f"platform layer: {layer}")
        state = "disabled" if name in disabled else ("enabled" if enabled_by else "available")
        toolsets.append({
            "name": name,
            "state": state,
            "enabled_by": enabled_by,
            "explicitly_disabled": name in disabled,
            "risk": TOOLSET_RISK.get(name, "unknown"),
            "tool_count": len(tools),
            "tools": tools,
            "known_to_registry": name in registry,
        })
    return {
        "profile": profile,
        "registry_source": reg["source"],
        "enabled": enabled,
        "disabled": disabled,
        "platform_layers": platform_layers,
        "toolsets": toolsets,
        "partial_application_note": (
            "Hermes filters at toolset granularity (agent.disabled_toolsets). Partial "
            "selection inside a toolset is expressed as a ChangeSet finding plus a "
            "profile-specific substitute toolset recommendation, not a per-tool config key."
        ),
    }


def partial_application_plan(profile: str, toolset: str, wanted_tools: list[str]) -> dict[str, Any]:
    """Plan a partial toolset application honestly against Hermes' real granularity."""
    inv = toolset_registry()
    tools = inv["registry"].get(toolset, [])
    if not tools:
        raise KeyError(f"unknown toolset: {toolset}")
    wanted = [t for t in wanted_tools if t in tools]
    excluded = [t for t in tools if t not in wanted]
    full = not excluded
    return {
        "profile": profile,
        "toolset": toolset,
        "wanted_tools": wanted,
        "excluded_tools": excluded,
        "applies_cleanly": full,
        "config_patch": {"op": "add-to-list", "path": "/toolsets", "value": toolset},
        "findings": [] if full else [{
            "severity": "warning",
            "scope": "toolsets",
            "message": (
                f"Hermes enables toolsets atomically; enabling '{toolset}' also exposes: "
                + ", ".join(excluded)
            ),
            "recommendation": "Gate the excluded tools via profile instructions/authority policy, or use a substitute toolset.",
        }],
    }
