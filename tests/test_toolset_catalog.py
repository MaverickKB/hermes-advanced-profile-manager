from __future__ import annotations

import sys

sys.path.insert(0, "webui")

import pytest

import toolset_catalog


@pytest.fixture(autouse=True)
def no_live_registry(monkeypatch):
    monkeypatch.setattr(toolset_catalog, "extract_live_registry", lambda timeout=30.0: None)


def test_inventory_states(iso):
    inv = toolset_catalog.toolset_inventory("alpha")
    by_name = {t["name"]: t for t in inv["toolsets"]}
    assert by_name["web"]["state"] == "enabled"
    assert "profile toolsets list" in by_name["web"]["enabled_by"]
    assert by_name["browser"]["state"] == "disabled"
    assert by_name["kanban"]["state"] == "available"


def test_inventory_lists_real_tools_with_risk(iso):
    inv = toolset_catalog.toolset_inventory("alpha")
    file_ts = next(t for t in inv["toolsets"] if t["name"] == "file")
    tools = {t["name"]: t for t in file_ts["tools"]}
    assert tools["read_file"]["risk"] == "read-only"
    assert tools["write_file"]["risk"] == "local-write"


def test_partial_application_full_selection_clean(iso):
    plan = toolset_catalog.partial_application_plan("alpha", "clarify", ["clarify"])
    assert plan["applies_cleanly"] is True
    assert plan["findings"] == []


def test_partial_application_partial_selection_warns(iso):
    plan = toolset_catalog.partial_application_plan("alpha", "file", ["read_file", "search_files"])
    assert plan["applies_cleanly"] is False
    assert plan["excluded_tools"] == ["patch", "write_file"]
    assert plan["findings"][0]["severity"] == "warning"


def test_partial_application_unknown_toolset(iso):
    with pytest.raises(KeyError):
        toolset_catalog.partial_application_plan("alpha", "no-such-toolset", [])
