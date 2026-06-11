"""MCP server and provider control surface.

Active controls, not passive lists: provenance, transport details, env
requirements (names only), enable/disable, connection tests, stdio tool
discovery, provider usage maps, auth tests, and completion tests.
"""
from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import urllib.request
from typing import Any

from env_auth import env_path, global_env_path, parse_env
from hermes_paths import backup_file, config_path, dump_yaml, load_profile_config, read_text, write_audit

MCP_PROTOCOL_VERSION = "2024-11-05"


# ----------------------------------------------------------------- MCP side

def _mcp_block(cfg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    for key in ("mcp_servers", "mcp"):
        block = cfg.get(key)
        if isinstance(block, dict):
            servers = block.get("servers") if isinstance(block.get("servers"), dict) else block
            if isinstance(servers, dict):
                return key, servers
    return "mcp_servers", {}


def mcp_inventory(profile: str) -> dict[str, Any]:
    cfg = load_profile_config(profile)
    key, servers = _mcp_block(cfg)
    out = []
    for name, server in servers.items():
        if not isinstance(server, dict):
            continue
        command = str(server.get("command") or "")
        url = str(server.get("url") or server.get("base_url") or "")
        transport = "stdio" if command else ("http/sse" if url else "unknown")
        env_map = server.get("env") if isinstance(server.get("env"), dict) else {}
        enabled_raw = server.get("enabled", True)
        enabled = str(enabled_raw).strip().lower() not in {"false", "0", "no", "off"}
        out.append({
            "name": str(name),
            "transport": transport,
            "command": command,
            "args": [str(a) for a in (server.get("args") or [])],
            "url": url,
            "enabled": enabled,
            "required_env_keys": sorted(str(k) for k in env_map),
            "provenance": {"config_path": str(config_path(profile)), "config_key": f"{key}.{name}"},
        })
    return {"profile": profile, "config_key": key, "servers": sorted(out, key=lambda x: x["name"]), "count": len(out)}


def mcp_set_enabled(profile: str, server: str, enabled: bool, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise ValueError("confirm=true required to change MCP server state")
    cfg = load_profile_config(profile)
    key, servers = _mcp_block(cfg)
    if server not in servers or not isinstance(servers[server], dict):
        raise KeyError(f"MCP server not found: {server}")
    cp = config_path(profile)
    backup = backup_file(profile, cp, "config")
    servers[server]["enabled"] = bool(enabled)
    cp.write_text(dump_yaml(cfg), encoding="utf-8")
    write_audit("mcp_set_enabled", profile, {"server": server, "enabled": bool(enabled), "backup": str(backup)})
    return {"ok": True, "backup": str(backup), "inventory": mcp_inventory(profile)}


def mcp_upsert_server(profile: str, server: str, spec: dict[str, Any], confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise ValueError("confirm=true required to edit MCP servers")
    server = str(server).strip()
    if not server:
        raise ValueError("server name required")
    allowed = {k: v for k, v in spec.items() if k in {"command", "args", "url", "env", "enabled", "transport"}}
    if isinstance(allowed.get("env"), dict):
        # env mapping in config carries key names / ${refs}; reject raw long secrets
        for k, v in allowed["env"].items():
            sval = str(v or "")
            if len(sval) > 12 and not sval.startswith("${"):
                raise ValueError(f"env value for {k} looks like an inline secret; use ${{VAR}} references")
    cfg = load_profile_config(profile)
    key, servers = _mcp_block(cfg)
    block = cfg.setdefault(key, {})
    if isinstance(block.get("servers"), dict):
        block = block["servers"]
    cp = config_path(profile)
    backup = backup_file(profile, cp, "config") if cp.exists() else None
    block[server] = {**(block.get(server) if isinstance(block.get(server), dict) else {}), **allowed}
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(dump_yaml(cfg), encoding="utf-8")
    write_audit("mcp_upsert_server", profile, {"server": server, "fields": sorted(allowed), "backup": str(backup) if backup else None})
    return {"ok": True, "backup": str(backup) if backup else None, "inventory": mcp_inventory(profile)}


def _profile_env(profile: str) -> dict[str, str]:
    merged = dict(os.environ)
    for path in (global_env_path(), env_path(profile)):
        if path.exists():
            for e in parse_env(read_text(path)):
                merged[e["key"]] = e["value"]
    return merged


def _stdio_mcp_tools(command: str, args: list[str], env: dict[str, str], timeout: float = 12.0) -> dict[str, Any]:
    """Minimal stdio MCP handshake: initialize → initialized → tools/list."""
    proc = subprocess.Popen(
        [command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=env, text=True,
    )
    try:
        def send(obj: dict[str, Any]) -> None:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()

        def recv(expect_id: int) -> dict[str, Any] | None:
            assert proc.stdout is not None
            import time
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ready, _, _ = select.select([proc.stdout], [], [], 0.25)
                if not ready:
                    if proc.poll() is not None:
                        return None
                    continue
                line = proc.stdout.readline()
                if not line:
                    return None
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                if msg.get("id") == expect_id:
                    return msg
            return None

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "hermes-advanced-profile-manager", "version": "0.1"},
        }})
        init = recv(1)
        if not init or init.get("error"):
            return {"ok": False, "stage": "initialize", "error": (init or {}).get("error") or "no response"}
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_msg = recv(2)
        if not tools_msg or tools_msg.get("error"):
            return {"ok": False, "stage": "tools/list", "error": (tools_msg or {}).get("error") or "no response"}
        tools = (tools_msg.get("result") or {}).get("tools") or []
        server_info = (init.get("result") or {}).get("serverInfo") or {}
        return {
            "ok": True,
            "server_info": {"name": server_info.get("name"), "version": server_info.get("version")},
            "tool_count": len(tools),
            "tools": [{
                "name": t.get("name"),
                "description": str(t.get("description") or "")[:200],
                "risk": _classify_tool_risk(str(t.get("name") or ""), str(t.get("description") or "")),
            } for t in tools if isinstance(t, dict)],
        }
    finally:
        proc.kill()
        proc.wait(timeout=5)


WRITE_MARKERS = ("create", "update", "delete", "write", "set_", "add_", "remove", "post", "send", "run_", "execute", "modify", "close", "assign")


def _classify_tool_risk(name: str, description: str) -> str:
    blob = f"{name} {description}".lower()
    if any(m in blob for m in WRITE_MARKERS):
        return "write/high"
    return "read/low"


def mcp_test(profile: str, server: str) -> dict[str, Any]:
    inv = mcp_inventory(profile)
    entry = next((s for s in inv["servers"] if s["name"] == server), None)
    if not entry:
        raise KeyError(f"MCP server not found: {server}")
    result: dict[str, Any] = {"profile": profile, "server": server, "transport": entry["transport"]}
    if entry["transport"] == "stdio":
        command = entry["command"]
        resolved = command if os.path.isabs(command) else shutil.which(command)
        if not resolved or not os.path.exists(resolved):
            result.update({"ok": False, "stage": "command", "error": f"command not found: {command}"})
        else:
            result.update(_stdio_mcp_tools(resolved, entry["args"], _profile_env(profile)))
    elif entry["transport"] == "http/sse":
        try:
            req = urllib.request.Request(entry["url"], method="GET", headers={"Accept": "application/json, text/event-stream"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                result.update({"ok": True, "stage": "http", "status": resp.status})
        except Exception as exc:
            result.update({"ok": False, "stage": "http", "error": f"{type(exc).__name__}: {exc}"})
    else:
        result.update({"ok": False, "stage": "transport", "error": "unknown transport"})
    write_audit("mcp_test", profile, {"server": server, "ok": result.get("ok"), "tool_count": result.get("tool_count")})
    return result


# ------------------------------------------------------------ provider side

def provider_inventory(profile: str) -> dict[str, Any]:
    cfg = load_profile_config(profile)
    cp = str(config_path(profile))
    providers = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    model = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    primary = str(model.get("provider") or "")
    fallbacks = cfg.get("fallback_providers") or []
    delegation = cfg.get("delegation") if isinstance(cfg.get("delegation"), dict) else {}
    auxiliary = cfg.get("auxiliary") if isinstance(cfg.get("auxiliary"), dict) else {}
    env = _profile_env(profile)

    usage: dict[str, list[str]] = {}
    if primary:
        usage.setdefault(primary, []).append(f"primary (model.default={model.get('default')})")
    for fb in fallbacks:
        if isinstance(fb, dict) and fb.get("provider"):
            usage.setdefault(str(fb["provider"]), []).append(f"fallback ({fb.get('model')})")
    if delegation.get("provider"):
        usage.setdefault(str(delegation["provider"]), []).append(f"delegation ({delegation.get('model')})")
    for aux_name, aux in auxiliary.items():
        if isinstance(aux, dict) and aux.get("provider"):
            usage.setdefault(str(aux["provider"]), []).append(f"auxiliary:{aux_name} ({aux.get('model')})")

    names = sorted(set(providers) | set(usage))
    out = []
    for name in names:
        pcfg = providers.get(name) if isinstance(providers.get(name), dict) else {}
        key_env = str(pcfg.get("key_env") or pcfg.get("api_key_env") or "")
        out.append({
            "name": name,
            "configured": name in providers,
            "base_url": str(pcfg.get("base_url") or ""),
            "api_mode": str(pcfg.get("api_mode") or ""),
            "default_model": str(pcfg.get("default_model") or ""),
            "context_length": pcfg.get("context_length"),
            "key_env": key_env,
            "auth_required": bool(key_env),
            "auth_key_present": bool(key_env and env.get(key_env)),
            "usage": usage.get(name, []) or (["declared only (unused)"] if name in providers else []),
            "provenance": {"config_path": cp, "config_key": f"providers.{name}" if name in providers else "referenced-by-usage-only"},
        })
    return {
        "profile": profile,
        "primary_provider": primary,
        "primary_model": str(model.get("default") or ""),
        "providers": out,
        "fallback_routes": [fb for fb in fallbacks if isinstance(fb, dict)],
    }


def _provider_base_and_key(profile: str, provider: str) -> tuple[str, str]:
    cfg = load_profile_config(profile)
    providers = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    pcfg = providers.get(provider) if isinstance(providers.get(provider), dict) else {}
    base = str(pcfg.get("base_url") or "")
    if not base:
        for fb in cfg.get("fallback_providers") or []:
            if isinstance(fb, dict) and str(fb.get("provider")) == provider and fb.get("base_url"):
                base = str(fb["base_url"])
                break
    key_env = str(pcfg.get("key_env") or pcfg.get("api_key_env") or "")
    key = _profile_env(profile).get(key_env, "") if key_env else ""
    return base, key


def provider_test_auth(profile: str, provider: str) -> dict[str, Any]:
    base, key = _provider_base_and_key(profile, provider)
    if not base:
        return {"ok": False, "provider": provider, "stage": "config", "error": "no base_url for this provider (managed/native auth providers are tested by Hermes itself)"}
    endpoint = base.rstrip("/") + "/models"
    req = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read(2_000_000).decode("utf-8", errors="replace"))
        models = []
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, list):
            models = [str(m.get("id")) if isinstance(m, dict) else str(m) for m in data]
        result = {"ok": True, "provider": provider, "endpoint": endpoint, "model_count": len(models), "models": sorted(set(models))[:100]}
    except Exception as exc:
        result = {"ok": False, "provider": provider, "endpoint": endpoint, "error": f"{type(exc).__name__}: {exc}"}
    write_audit("provider_test_auth", profile, {"provider": provider, "ok": result["ok"]})
    return result


def provider_test_completion(profile: str, provider: str, model: str) -> dict[str, Any]:
    base, key = _provider_base_and_key(profile, provider)
    if not base:
        return {"ok": False, "provider": provider, "stage": "config", "error": "no base_url for this provider"}
    endpoint = base.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "max_tokens": 8,
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, method="POST", headers={"Content-Type": "application/json"})
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read(2_000_000).decode("utf-8", errors="replace"))
        choice = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        result = {"ok": True, "provider": provider, "model": model, "endpoint": endpoint, "reply_preview": str(choice)[:120]}
    except Exception as exc:
        result = {"ok": False, "provider": provider, "model": model, "endpoint": endpoint, "error": f"{type(exc).__name__}: {exc}"}
    write_audit("provider_test_completion", profile, {"provider": provider, "model": model, "ok": result["ok"]})
    return result


def provider_upsert(profile: str, provider: str, spec: dict[str, Any], confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise ValueError("confirm=true required to edit providers")
    provider = str(provider).strip()
    if not provider:
        raise ValueError("provider name required")
    allowed = {k: v for k, v in spec.items() if k in {"base_url", "api_mode", "default_model", "context_length", "key_env", "api_key_env"}}
    for k, v in allowed.items():
        if "key" in k and isinstance(v, str) and len(v) > 40:
            raise ValueError(f"{k} must be an env var NAME, not a secret value")
    cfg = load_profile_config(profile)
    providers = cfg.setdefault("providers", {})
    if not isinstance(providers, dict):
        cfg["providers"] = providers = {}
    cp = config_path(profile)
    backup = backup_file(profile, cp, "config") if cp.exists() else None
    providers[provider] = {**(providers.get(provider) if isinstance(providers.get(provider), dict) else {}), **allowed}
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(dump_yaml(cfg), encoding="utf-8")
    write_audit("provider_upsert", profile, {"provider": provider, "fields": sorted(allowed), "backup": str(backup) if backup else None})
    return {"ok": True, "backup": str(backup) if backup else None, "inventory": provider_inventory(profile)}


def set_model_route(profile: str, route: str, provider: str, model: str, confirm: bool) -> dict[str, Any]:
    """Safe route replacement for primary/delegation routes."""
    if not confirm:
        raise ValueError("confirm=true required to change model routes")
    if route not in {"primary", "delegation"}:
        raise ValueError("route must be 'primary' or 'delegation'")
    cfg = load_profile_config(profile)
    cp = config_path(profile)
    backup = backup_file(profile, cp, "config") if cp.exists() else None
    if route == "primary":
        block = cfg.setdefault("model", {})
        if not isinstance(block, dict):
            cfg["model"] = block = {}
        block["provider"] = provider
        block["default"] = model
    else:
        block = cfg.setdefault("delegation", {})
        if not isinstance(block, dict):
            cfg["delegation"] = block = {}
        block["provider"] = provider
        block["model"] = model
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(dump_yaml(cfg), encoding="utf-8")
    write_audit("set_model_route", profile, {"route": route, "provider": provider, "model": model, "backup": str(backup) if backup else None})
    return {"ok": True, "backup": str(backup) if backup else None, "inventory": provider_inventory(profile)}
