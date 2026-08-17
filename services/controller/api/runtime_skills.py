"""Selected-runtime routing for the Skills API."""

from __future__ import annotations

from typing import Any

from api.backend_catalog import JAEGER_BACKEND_ID


class RuntimeSkillError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def selected_runtime_owns_skills() -> bool:
    from api.backend_selector import get_active_backend
    from api.config import get_config

    return get_active_backend(get_config()) == JAEGER_BACKEND_ID


def _require_jaeger_skills() -> None:
    from api.ares_capabilities import capability_contract_for_backend

    negotiated = capability_contract_for_backend(JAEGER_BACKEND_ID)
    contract = negotiated.get("runtime_contract") or {}
    feature = (contract.get("features") or {}).get("skills") or {}
    if negotiated.get("negotiated") is not True or feature.get("available") is not True:
        detail = negotiated.get("error") or "the selected Jaeger runtime does not advertise Skills support"
        raise RuntimeSkillError(str(detail), 503)


def _query(what: str, args: dict[str, Any] | None = None) -> Any:
    _require_jaeger_skills()
    try:
        from api.providers.jaeger.streaming import query_local_companion

        return query_local_companion(what, args or {})
    except RuntimeSkillError:
        raise
    except Exception as exc:
        raise RuntimeSkillError(f"Jaeger Skills query failed: {exc}", 502) from exc


def _command(cmd: str, args: dict[str, Any] | None = None) -> Any:
    _require_jaeger_skills()
    try:
        from api.providers.jaeger.streaming import command_local_companion

        return command_local_companion(cmd, args or {})
    except RuntimeSkillError:
        raise
    except Exception as exc:
        raise RuntimeSkillError(f"Jaeger Skills command failed: {exc}", 502) from exc


def list_runtime_skills(category: str | None = None) -> dict[str, Any]:
    payload = _query("list_skills")
    if not isinstance(payload, dict) or not isinstance(payload.get("skills"), list):
        raise RuntimeSkillError("Jaeger returned an invalid skill catalog", 502)
    if category:
        payload = {**payload, "skills": [
            row for row in payload["skills"]
            if isinstance(row, dict) and row.get("category") == category
        ]}
    return payload


def get_runtime_skill(name: str, linked_file: str | None = None) -> dict[str, Any]:
    payload = _query("get_skill", {"name": name, "file": linked_file})
    if not isinstance(payload, dict):
        raise RuntimeSkillError("Jaeger returned invalid skill content", 502)
    return payload


def install_runtime_skill(name: str, content: str, category: str = "") -> dict[str, Any]:
    return _command("install_skill", {"name": name, "content": content, "category": category})


def clone_runtime_skill(name: str) -> dict[str, Any]:
    return _command("clone_skill", {"name": name})


def remove_runtime_skill(name: str) -> dict[str, Any]:
    return _command("remove_skill", {"name": name})


def toggle_runtime_skill(name: str, enabled: bool) -> dict[str, Any]:
    return _command("enable_skill" if enabled else "disable_skill", {"name": name})


def runtime_skill_usage() -> dict[str, Any]:
    skills = list_runtime_skills().get("skills", [])
    return {
        "usage": {},
        "skill_names": sorted(str(row.get("name")) for row in skills if isinstance(row, dict)),
        "total_invocations": 0,
        "unique_skills_used": 0,
        "owner": "jaeger",
        "usage_available": False,
    }
