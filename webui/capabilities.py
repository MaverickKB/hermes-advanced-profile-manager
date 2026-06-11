"""Runtime capability detection for the installed hermes-agent.

Some surfaces this manager edits are upstream-native Hermes config; others
are extensions pioneered in forks (and offered here as the forward-compatible
north star). The UI must say which is which honestly: writing an extension
key into config.yaml is harmless but inert on a runtime that does not
implement it.

Detection scans the installed hermes-agent source (when present beside the
Hermes home) for the implementing symbols, cached against the checkout's
HEAD/mtime. No network, no dependence on any particular fork.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import hermes_paths
from hermes_paths import hermes_home

# surface -> source symbols that prove the runtime implements it
EXTENSION_MARKERS: dict[str, list[str]] = {
    "profile_delegation": ["profile_delegation", "delegate_profile"],
    "channel_profiles": ["channel_profiles"],
    "skill_groups": ["skill_groups"],
}

NATIVE_SURFACES = [
    "model", "providers", "fallback_providers", "auxiliary", "delegation-worker",
    "mcp_servers", "toolsets", "disabled_toolsets", "skills.disabled", "agent.system_prompt",
]

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".github", "docs", "tests"}
MAX_FILES = 4000


def _agent_repo() -> Path | None:
    candidates = [
        hermes_home() / "hermes-agent",
        hermes_home().parent / "hermes-agent",
    ]
    for c in candidates:
        if (c / "model_tools.py").exists() or (c / "cli.py").exists():
            return c
    return None


def _repo_fingerprint(repo: Path) -> str:
    head = repo / ".git" / "HEAD"
    try:
        if head.exists():
            ref = head.read_text(encoding="utf-8").strip()
            if ref.startswith("ref: "):
                ref_file = repo / ".git" / ref[5:]
                if ref_file.exists():
                    return ref_file.read_text(encoding="utf-8").strip()
            return ref
    except Exception:
        pass
    try:
        return str((repo / "model_tools.py").stat().st_mtime)
    except Exception:
        return "unknown"


def _cache_path() -> Path:
    return hermes_paths.STATE / "agent-capabilities.json"


def _scan(repo: Path) -> dict[str, bool]:
    found = {key: False for key in EXTENSION_MARKERS}
    remaining = {m for markers in EXTENSION_MARKERS.values() for m in markers}
    count = 0
    for path in repo.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        count += 1
        if count > MAX_FILES or not remaining:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for marker in list(remaining):
            if marker in text:
                remaining.discard(marker)
    for key, markers in EXTENSION_MARKERS.items():
        found[key] = all(m not in remaining for m in markers)
    return found


def agent_capabilities(refresh: bool = False) -> dict[str, Any]:
    repo = _agent_repo()
    if repo is None:
        return {
            "agent_repo": None,
            "source": "no-agent-source-found",
            "extensions": {key: {"runtime_support": "unknown",
                                 "note": "hermes-agent source not found beside the Hermes home; cannot verify runtime support"}
                           for key in EXTENSION_MARKERS},
            "native_surfaces": NATIVE_SURFACES,
        }
    fingerprint = _repo_fingerprint(repo)
    cache = _cache_path()
    if not refresh and cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint:
                return cached["capabilities"]
        except Exception:
            pass
    found = _scan(repo)
    capabilities = {
        "agent_repo": str(repo),
        "source": "scanned-agent-source",
        "extensions": {
            key: {
                "runtime_support": "implemented" if supported else "not-implemented",
                "note": ("the installed hermes-agent implements this surface"
                         if supported else
                         "extension surface: config is forward-compatible but the installed hermes-agent ignores it"),
            }
            for key, supported in found.items()
        },
        "native_surfaces": NATIVE_SURFACES,
    }
    try:
        hermes_paths.STATE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"fingerprint": fingerprint, "capabilities": capabilities}, indent=2), encoding="utf-8")
    except Exception:
        pass
    return capabilities
