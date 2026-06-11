from __future__ import annotations

import sys

sys.path.insert(0, "webui")

import pytest

import library_store


def test_builtin_domains_and_roles_present(iso):
    domains = {d["name"] for d in library_store.list_domains()}
    assert {"coding", "rmm-support", "profile-management"} <= domains
    roles = {r["name"] for r in library_store.list_roles()}
    assert {"orchestrator", "analyst", "worker"} <= roles


def test_create_custom_domain_inline(iso):
    result = library_store.upsert_domain("hardware-lab", {"description": "Bench work."})
    entry = next(d for d in result["domains"] if d["name"] == "hardware-lab")
    assert entry["source"] == "custom"
    library_store.delete_domain("hardware-lab")
    assert "hardware-lab" not in {d["name"] for d in library_store.list_domains()}


def test_customized_builtin_role(iso):
    result = library_store.upsert_role("analyst", {"description": "Customized analyst."})
    entry = next(r for r in result["roles"] if r["name"] == "analyst")
    assert entry["source"] == "customized"


def test_builtin_domain_cannot_be_deleted(iso):
    with pytest.raises(KeyError):
        library_store.delete_domain("coding")


