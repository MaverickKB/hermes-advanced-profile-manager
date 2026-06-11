from __future__ import annotations

import sys

sys.path.insert(0, "webui")

import pytest

import channels
from hermes_paths import config_path, dump_yaml, load_profile_config


def _set_block(profile, platform, block):
    cfg = load_profile_config(profile)
    cfg[platform] = block
    config_path(profile).write_text(dump_yaml(cfg), encoding="utf-8")


def test_view_reports_all_platforms(iso):
    view = channels.channels_view("alpha")
    names = {p["platform"] for p in view["platforms"]}
    assert names == {"discord", "telegram", "slack", "whatsapp", "matrix", "mattermost"}
    discord = next(p for p in view["platforms"] if p["platform"] == "discord")
    assert discord["configured"] is False
    assert {t["env"] for t in discord["tokens"]} == {"DISCORD_BOT_TOKEN"}
    assert discord["token_ready"] is False  # not in any env


def test_view_summarizes_configured_platform(iso):
    _set_block("alpha", "discord", {
        "require_mention": True,
        "allowed_channels": ["111", "222"],
        "channel_prompts": {"111": "be brief"},
        "channel_profiles": {"111": "beta", "999": "ghost"},
    })
    view = channels.channels_view("alpha")
    discord = next(p for p in view["platforms"] if p["platform"] == "discord")
    assert discord["configured"] and discord["require_mention"] is True
    assert discord["access"]["allowed_channels"] == ["111", "222"]
    assert discord["channel_prompts"] == 1
    routing = {r["channel"]: r for r in discord["routing"]}
    assert routing["111"]["valid"] is True
    assert routing["999"]["valid"] is False
    assert discord["routing_invalid"] == 1


def test_token_presence_from_profile_env(iso):
    (iso["alpha"] / ".env").write_text("DISCORD_BOT_TOKEN=secretvalue\n", encoding="utf-8")
    view = channels.channels_view("alpha")
    discord = next(p for p in view["platforms"] if p["platform"] == "discord")
    assert discord["token_ready"] is True
    import json
    assert "secretvalue" not in json.dumps(view)


def test_set_platform_block_with_backup(iso):
    result = channels.set_platform_block("alpha", "telegram", "telegram:\n  allowed_chats: ['123']\n  reactions: true\n", confirm=True)
    assert result["ok"] and result["backup"]
    cfg = load_profile_config("alpha")
    assert cfg["telegram"]["allowed_chats"] == ["123"]


def test_set_platform_block_rejects_inline_secret(iso):
    with pytest.raises(ValueError, match="inline secret"):
        channels.set_platform_block("alpha", "discord", "discord:\n  bot_token: abcdefghijklmnop\n", confirm=True)


def test_empty_block_removes_platform(iso):
    _set_block("alpha", "telegram", {"allowed_chats": ["1"]})
    channels.set_platform_block("alpha", "telegram", "telegram:\n", confirm=True)
    cfg = load_profile_config("alpha")
    assert "telegram" not in cfg


def test_routing_ops_validate_targets(iso):
    channels.set_routing("alpha", "discord", [{"op": "set", "channel": "111", "profile": "beta"}], confirm=True)
    cfg = load_profile_config("alpha")
    assert cfg["discord"]["channel_profiles"]["111"] == "beta"
    with pytest.raises(ValueError, match="does not exist"):
        channels.set_routing("alpha", "discord", [{"op": "set", "channel": "222", "profile": "ghost"}], confirm=True)
    channels.set_routing("alpha", "discord", [{"op": "remove", "channel": "111"}], confirm=True)
    assert load_profile_config("alpha")["discord"]["channel_profiles"] == {}


def test_routing_only_on_platforms_with_routing_surface(iso):
    with pytest.raises(ValueError, match="no channel routing"):
        channels.set_routing("alpha", "telegram", [{"op": "set", "channel": "1", "profile": "beta"}], confirm=True)
