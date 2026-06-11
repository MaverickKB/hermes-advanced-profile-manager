"""Communication channel (platform bot) configuration per profile.

Hermes profiles scope platform-bot behavior through upstream-native config
blocks (discord, telegram, slack, whatsapp, matrix, mattermost): access
policy (allowed channels/chats/rooms, require_mention, free-response lists),
reactions, channel prompts. Credentials are env tokens, never config values.
The per-channel profile routing map (discord.channel_profiles) is an
extension surface flagged through capability detection.
"""
from __future__ import annotations

from typing import Any

from env_auth import env_path, global_env_path, parse_env
from hermes_paths import backup_file, config_path, dump_yaml, load_profile_config, parse_yaml_text, profiles_root, read_text, write_audit

import os

# platform -> (access list keys, token env names checked for presence)
PLATFORMS: dict[str, dict[str, Any]] = {
    "discord": {
        "access_keys": ["allowed_channels", "free_response_channels"],
        "token_envs": ["DISCORD_BOT_TOKEN"],
        "routing_key": "channel_profiles",
    },
    "telegram": {
        "access_keys": ["allowed_chats"],
        "token_envs": ["TELEGRAM_BOT_TOKEN"],
    },
    "slack": {
        "access_keys": ["allowed_channels", "free_response_channels"],
        "token_envs": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
    },
    "whatsapp": {
        "access_keys": ["allowed_chats"],
        "token_envs": [],
    },
    "matrix": {
        "access_keys": ["allowed_rooms", "free_response_rooms"],
        "token_envs": ["MATRIX_ACCESS_TOKEN"],
    },
    "mattermost": {
        "access_keys": ["allowed_channels", "free_response_channels"],
        "token_envs": ["MATTERMOST_TOKEN"],
    },
}

SECRETISH = ("token", "secret", "password", "api_key", "apikey")


def _available_env(profile: str) -> set[str]:
    keys = set(os.environ.keys())
    for path in (global_env_path(), env_path(profile)):
        if path.exists():
            keys |= {e["key"] for e in parse_env(read_text(path))}
    return keys


def _profile_names() -> set[str]:
    root = profiles_root()
    if not root.exists():
        return set()
    return {d.name for d in root.iterdir() if d.is_dir()} | {"default"}


def channels_view(profile: str) -> dict[str, Any]:
    cfg = load_profile_config(profile)
    env_keys = _available_env(profile)
    names = _profile_names()
    platforms = []
    for platform, spec in PLATFORMS.items():
        block = cfg.get(platform) if isinstance(cfg.get(platform), dict) else None
        access: dict[str, list[str]] = {}
        routing: list[dict[str, Any]] = []
        if block:
            for key in spec["access_keys"]:
                value = block.get(key)
                if isinstance(value, list):
                    access[key] = [str(v) for v in value]
            routing_key = spec.get("routing_key")
            if routing_key and isinstance(block.get(routing_key), dict):
                for channel, target in block[routing_key].items():
                    routing.append({
                        "channel": str(channel),
                        "profile": str(target),
                        "valid": str(target) in names,
                    })
        tokens = [{"env": t, "present": t in env_keys} for t in spec["token_envs"]]
        platforms.append({
            "platform": platform,
            "configured": block is not None,
            "field_count": len(block) if block else 0,
            "require_mention": bool(block.get("require_mention")) if block else None,
            "reactions": bool(block.get("reactions")) if block and "reactions" in block else None,
            "access": access,
            "channel_prompts": len(block.get("channel_prompts") or {}) if block else 0,
            "routing": routing,
            "routing_invalid": sum(1 for r in routing if not r["valid"]),
            "tokens": tokens,
            "token_ready": all(t["present"] for t in tokens) if tokens else None,
            "block_yaml": dump_yaml({platform: block}) if block else f"{platform}:\n  # not configured\n",
        })
    return {
        "profile": profile,
        "config_path": str(config_path(profile)),
        "platforms": platforms,
        "note": "Tokens live in env (names shown, values never displayed). The gateway serves whichever platforms have credentials; these blocks scope this profile's behavior on them.",
    }


def _reject_inline_secrets(block: dict[str, Any], platform: str) -> None:
    def walk(obj: Any, path: str):
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{path}.{k}"
                if isinstance(v, str) and any(s in str(k).lower() for s in SECRETISH) and len(v) > 12 and not v.startswith("${"):
                    raise ValueError(f"{p} looks like an inline secret; platform credentials belong in env (e.g. {platform.upper()}_BOT_TOKEN), not config")
                walk(v, p)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
    walk(block, platform)


def set_platform_block(profile: str, platform: str, block_yaml: str, confirm: bool) -> dict[str, Any]:
    """Replace one platform's config block from YAML, with validation + backup."""
    if not confirm:
        raise ValueError("confirm=true required to edit channel configuration")
    if platform not in PLATFORMS:
        raise KeyError(f"unknown platform: {platform}")
    data, issues = parse_yaml_text(block_yaml)
    if issues or not isinstance(data, dict):
        raise ValueError("platform block must be valid YAML mapping")
    block = data.get(platform, data)  # accept either wrapped or bare mapping
    if block is not None and not isinstance(block, dict):
        raise ValueError(f"the {platform} block must be a mapping (or empty to remove)")
    if isinstance(block, dict):
        _reject_inline_secrets(block, platform)
    cfg = load_profile_config(profile)
    cp = config_path(profile)
    if not cp.exists():
        raise FileNotFoundError(f"no config for {profile}")
    backup = backup_file(profile, cp, "config")
    if block:
        cfg[platform] = block
    else:
        cfg.pop(platform, None)
    cp.write_text(dump_yaml(cfg), encoding="utf-8")
    write_audit("set_platform_block", profile, {"platform": platform, "removed": not block, "backup": str(backup)})
    return {"ok": True, "backup": str(backup), "view": channels_view(profile)}


def set_routing(profile: str, platform: str, ops: list[dict[str, Any]], confirm: bool) -> dict[str, Any]:
    """Edit channel->profile routing: ops [{op:set|remove, channel, profile?}]."""
    if not confirm:
        raise ValueError("confirm=true required to edit channel routing")
    spec = PLATFORMS.get(platform) or {}
    routing_key = spec.get("routing_key")
    if not routing_key:
        raise ValueError(f"{platform} has no channel routing surface")
    names = _profile_names()
    cfg = load_profile_config(profile)
    cp = config_path(profile)
    block = cfg.setdefault(platform, {})
    if not isinstance(block, dict):
        cfg[platform] = block = {}
    routing = block.setdefault(routing_key, {})
    if not isinstance(routing, dict):
        block[routing_key] = routing = {}
    applied = []
    for op in ops:
        action = str(op.get("op") or "")
        channel = str(op.get("channel") or "").strip()
        if not channel:
            raise ValueError("channel id required")
        if action == "set":
            target = str(op.get("profile") or "").strip()
            if target not in names:
                raise ValueError(f"routing target profile does not exist: {target}")
            routing[channel] = target
            applied.append({"op": "set", "channel": channel, "profile": target})
        elif action == "remove":
            routing.pop(channel, None)
            applied.append({"op": "remove", "channel": channel})
        else:
            raise ValueError(f"unsupported routing op: {action}")
    backup = backup_file(profile, cp, "config")
    cp.write_text(dump_yaml(cfg), encoding="utf-8")
    write_audit("set_channel_routing", profile, {"platform": platform, "ops": applied, "backup": str(backup)})
    return {"ok": True, "backup": str(backup), "view": channels_view(profile)}
