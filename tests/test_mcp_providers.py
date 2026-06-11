from __future__ import annotations

import json
import sys
import textwrap

sys.path.insert(0, "webui")

import pytest

import mcp_providers
from hermes_paths import load_profile_config


def test_mcp_inventory_provenance(iso):
    inv = mcp_providers.mcp_inventory("alpha")
    assert inv["count"] == 1
    server = inv["servers"][0]
    assert server["name"] == "alpha-mcp"
    assert server["transport"] == "stdio"
    assert server["required_env_keys"] == ["ALPHA_TOKEN"]
    assert server["provenance"]["config_key"] == "mcp_servers.alpha-mcp"


def test_mcp_set_enabled_backs_up(iso):
    result = mcp_providers.mcp_set_enabled("alpha", "alpha-mcp", False, confirm=True)
    assert result["ok"] and result["backup"]
    assert result["inventory"]["servers"][0]["enabled"] is False


def test_mcp_upsert_rejects_inline_secret_env(iso):
    with pytest.raises(ValueError):
        mcp_providers.mcp_upsert_server("alpha", "bad", {"command": "x", "env": {"TOKEN": "averylongsecretvalue"}}, confirm=True)


def test_mcp_upsert_accepts_env_references(iso):
    result = mcp_providers.mcp_upsert_server("alpha", "new-mcp", {"command": "/usr/bin/true", "env": {"TOKEN": "${TOKEN}"}}, confirm=True)
    names = {s["name"] for s in result["inventory"]["servers"]}
    assert "new-mcp" in names


def test_mcp_stdio_handshake_with_fake_server(iso, tmp_path):
    script = tmp_path / "fake_mcp.py"
    script.write_text(textwrap.dedent("""\
        import json, sys
        for line in sys.stdin:
            msg = json.loads(line)
            if msg.get("method") == "initialize":
                print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"serverInfo": {"name": "fake", "version": "1"}}}), flush=True)
            elif msg.get("method") == "tools/list":
                print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [
                    {"name": "list_devices", "description": "List devices"},
                    {"name": "create_ticket", "description": "Create a ticket"},
                ]}}), flush=True)
                break
    """), encoding="utf-8")
    result = mcp_providers._stdio_mcp_tools(sys.executable, [str(script)], dict(__import__("os").environ), timeout=10)
    assert result["ok"] is True
    assert result["tool_count"] == 2
    risks = {t["name"]: t["risk"] for t in result["tools"]}
    assert risks["list_devices"] == "read/low"
    assert risks["create_ticket"] == "write/high"


def test_provider_inventory_usage_map(iso):
    inv = mcp_providers.provider_inventory("alpha")
    by_name = {p["name"]: p for p in inv["providers"]}
    assert inv["primary_provider"] == "nous"
    assert any(u.startswith("primary") for u in by_name["nous"]["usage"])
    nous_api = by_name["nous-api"]
    assert any(u.startswith("fallback") for u in nous_api["usage"])
    assert any(u.startswith("delegation") for u in nous_api["usage"])
    assert nous_api["auth_required"] is True
    assert nous_api["auth_key_present"] is False  # NOUS_API_KEY not set anywhere
    assert json.dumps(inv).count("alphasecret123") == 0


def test_provider_upsert_rejects_secret_value(iso):
    with pytest.raises(ValueError):
        mcp_providers.provider_upsert("alpha", "x", {"key_env": "sk-" + "a" * 48}, confirm=True)


def test_set_model_route_primary(iso):
    result = mcp_providers.set_model_route("alpha", "primary", "nous-api", "Hermes-4-405B", confirm=True)
    assert result["ok"] and result["backup"]
    cfg = load_profile_config("alpha")
    assert cfg["model"] == {"provider": "nous-api", "default": "Hermes-4-405B"}


def test_set_model_route_delegation(iso):
    mcp_providers.set_model_route("alpha", "delegation", "nous", "hermes-4.1", confirm=True)
    cfg = load_profile_config("alpha")
    assert cfg["delegation"]["provider"] == "nous"
    assert cfg["delegation"]["model"] == "hermes-4.1"
