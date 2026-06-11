"""Evidence-backed profile readiness verdict.

Answers the acceptance question in one screen: "Can this profile safely and
effectively operate right now?" Verdict is composed from live route tests,
MCP connectivity, auth/env state, skills, worker boundaries, secret hygiene,
and duplicate-profile detection — never from config presence alone.
"""
from __future__ import annotations

from typing import Any

from env_auth import auth_status, env_status, required_env_findings
from hermes_paths import config_path, load_profile_config, profiles_root, read_text
from mcp_providers import mcp_inventory, mcp_test, provider_inventory, provider_test_auth


def _evidence(ok: bool | None, label: str, detail: str = "") -> dict[str, Any]:
    return {"ok": ok, "label": label, "detail": detail}


def _duplicate_candidates(profile: str) -> list[str]:
    """Profiles whose names differ only by separators/case — alias/retire candidates."""
    root = profiles_root()
    if not root.exists():
        return []
    norm = profile.replace("-", "").replace("_", "").replace(" ", "").lower()
    out = []
    for d in root.iterdir():
        if not d.is_dir() or d.name == profile:
            continue
        other = d.name.replace("-", "").replace("_", "").replace(" ", "").lower()
        if other == norm:
            out.append(d.name)
    return sorted(out)


def readiness_report(profile: str, live: bool = True) -> dict[str, Any]:
    cfg = load_profile_config(profile)
    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []
    blockers: list[str] = []

    if not config_path(profile).exists():
        return {
            "profile": profile, "verdict": "not-ready",
            "headline": f"No: {profile} has no config.yaml.",
            "evidence": [_evidence(False, "config", "config.yaml missing")],
            "warnings": [], "blockers": ["missing config.yaml"],
        }

    # Primary + fallback routes
    pinv = provider_inventory(profile)
    primary = pinv["primary_provider"]
    if not primary:
        blockers.append("no primary model route configured")
        evidence.append(_evidence(False, "primary route", "model.provider is empty"))
    elif live:
        test = provider_test_auth(profile, primary)
        if test.get("ok"):
            evidence.append(_evidence(True, "primary route", f"{primary}/{pinv['primary_model']} models endpoint reachable ({test.get('model_count')} models)"))
        elif "managed/native auth" in str(test.get("error", "")):
            evidence.append(_evidence(None, "primary route", f"{primary}/{pinv['primary_model']} uses Hermes-managed auth; not externally testable here"))
        else:
            warnings.append(f"primary route test failed: {test.get('error')}")
            evidence.append(_evidence(False, "primary route", str(test.get("error"))))
    else:
        evidence.append(_evidence(None, "primary route", f"{primary}/{pinv['primary_model']} (live test skipped)"))

    fallbacks = pinv.get("fallback_routes") or []
    if fallbacks and live:
        ok_count = 0
        for fb in fallbacks:
            name = str(fb.get("provider") or "custom")
            test = provider_test_auth(profile, name)
            if test.get("ok"):
                ok_count += 1
        if ok_count == len(fallbacks):
            evidence.append(_evidence(True, "fallback routes", f"{ok_count}/{len(fallbacks)} fallback routes reachable"))
        elif ok_count:
            warnings.append("some fallback routes unreachable")
            evidence.append(_evidence(None, "fallback routes", f"{ok_count}/{len(fallbacks)} fallback routes reachable"))
        else:
            warnings.append("no fallback route reachable")
            evidence.append(_evidence(False, "fallback routes", f"0/{len(fallbacks)} reachable"))
    elif not fallbacks:
        warnings.append("no fallback model route configured")
        evidence.append(_evidence(None, "fallback routes", "none configured"))

    # MCP connectivity + tool surface
    minv = mcp_inventory(profile)
    for server in minv["servers"]:
        if not server["enabled"]:
            evidence.append(_evidence(None, f"MCP {server['name']}", "disabled in config"))
            continue
        if live:
            test = mcp_test(profile, server["name"])
            if test.get("ok") and test.get("tool_count") is not None:
                tools = test.get("tools") or []
                high = sum(1 for t in tools if t.get("risk") == "write/high")
                evidence.append(_evidence(True, f"MCP {server['name']}", f"connects with {test['tool_count']} tools ({high} write/high-risk)"))
            elif test.get("ok"):
                evidence.append(_evidence(True, f"MCP {server['name']}", "endpoint reachable"))
            else:
                warnings.append(f"MCP {server['name']} failed: {test.get('error')}")
                evidence.append(_evidence(False, f"MCP {server['name']}", str(test.get("error"))))
        else:
            evidence.append(_evidence(None, f"MCP {server['name']}", "configured (live test skipped)"))

    # Auth + env
    auth = auth_status(profile)
    if auth["source"] == "missing":
        blockers.append("no auth source (no profile-local or default auth.json)")
        evidence.append(_evidence(False, "auth", "no auth.json found"))
    else:
        detail = f"{auth['source']}"
        if auth.get("stale"):
            warnings.append(f"auth.json updated_at older than {auth['stale_threshold_days']} days")
            detail += " (stale)"
        evidence.append(_evidence(not auth.get("stale"), "auth", detail))

    env = env_status(profile)
    evidence.append(_evidence(True, "env scope", env["scope"]))
    for f in required_env_findings(profile, cfg):
        if f["severity"] == "warning":
            warnings.append(f["message"])
            evidence.append(_evidence(False, "env keys", f["message"]))

    # Secrets hygiene: env values must be referenced, not embedded in config
    text = read_text(config_path(profile))
    inline_secret = False
    for line in text.splitlines():
        low = line.lower()
        if any(k in low for k in ("api_key:", "token:", "secret:", "password:")):
            val = line.split(":", 1)[1].strip().strip("'\"") if ":" in line else ""
            if val and not val.startswith("${") and not val.endswith("_ENV") and len(val) > 7 and "env" not in low.split(":")[0]:
                inline_secret = True
    if inline_secret:
        warnings.append("possible inline secret values in config.yaml; use env references")
        evidence.append(_evidence(False, "secrets", "possible inline secret values in config.yaml"))
    else:
        evidence.append(_evidence(True, "secrets", "secrets referenced externally, not embedded"))

    # Identity + skills presence
    from identity_files import identity_status
    ident = identity_status(profile)
    missing_identity = [f["name"] for f in ident["files"] if f["status"] == "missing" and f["name"] != "AGENTS.md"]
    if missing_identity:
        warnings.append("missing identity files: " + ", ".join(missing_identity))
        evidence.append(_evidence(False, "identity", "missing: " + ", ".join(missing_identity)))
    else:
        local = [f["name"] for f in ident["files"] if f["status"] == "profile-local"]
        evidence.append(_evidence(True, "identity", f"profile-local: {', '.join(local) or 'none (inherited)'}"))

    # Skill groups declared in config (skill_groups.enabled) must exist and be satisfied
    import skill_groups as sg
    declared_groups = sg.enabled_groups(profile)
    if declared_groups:
        from server import scan_skill_catalog
        catalog = scan_skill_catalog(profile)
        catalog_names = {s["name"] for s in catalog["skills"]}
        enabled_names = {s["name"] for s in catalog["skills"] if s["enabled"]}
        toolsets_list = [str(t) for t in (cfg.get("toolsets") or [])]
        for group_name in declared_groups:
            try:
                preview = sg.group_apply_preview(group_name, profile, catalog_names, enabled_names, toolsets_list)
            except KeyError:
                blockers.append(f"declared skill group '{group_name}' has no manifest")
                evidence.append(_evidence(False, f"group {group_name}", "declared in config but no manifest found"))
                continue
            problems = []
            if preview["missing_required_skills"]:
                problems.append("missing skills: " + ", ".join(preview["missing_required_skills"]))
            if preview["skills_to_enable"]:
                problems.append("not yet enabled: " + ", ".join(preview["skills_to_enable"]))
            if preview["forbidden_toolsets_present"]:
                problems.append("forbidden toolsets enabled: " + ", ".join(preview["forbidden_toolsets_present"]))
            if problems:
                warnings.append(f"skill group '{group_name}' unsatisfied: " + "; ".join(problems))
                evidence.append(_evidence(False, f"group {group_name}", "; ".join(problems)))
            else:
                evidence.append(_evidence(True, f"group {group_name}", "declared and satisfied"))
    else:
        evidence.append(_evidence(None, "skill groups", "none declared in config (skill_groups.enabled)"))

    # Worker / delegation boundary
    delegation = cfg.get("delegation") if isinstance(cfg.get("delegation"), dict) else {}
    if delegation.get("provider") or delegation.get("model"):
        evidence.append(_evidence(True, "worker route", f"delegation via {delegation.get('provider')}/{delegation.get('model')} (orchestrator_enabled={delegation.get('orchestrator_enabled')})"))
    else:
        evidence.append(_evidence(None, "worker route", "no delegation route configured"))

    # Duplicate / alias profiles
    dupes = _duplicate_candidates(profile)
    if dupes:
        warnings.append("possible duplicate/alias profiles: " + ", ".join(dupes))
        evidence.append(_evidence(None, "duplicates", ", ".join(dupes)))
    else:
        evidence.append(_evidence(True, "duplicates", "no near-duplicate profile names"))

    if blockers:
        verdict, headline = "not-ready", f"No: {'; '.join(blockers)}."
    elif warnings:
        verdict, headline = "ready-with-warnings", f"Yes, with {len(warnings)} warning(s)."
    else:
        verdict, headline = "ready", "Yes: all checks passed."
    return {
        "profile": profile,
        "verdict": verdict,
        "headline": headline,
        "evidence": evidence,
        "warnings": warnings,
        "blockers": blockers,
        "live": live,
    }
