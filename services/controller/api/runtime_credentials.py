"""Jaeger-owned credential operations exposed to ARES through the bridge.

ARES may learn which credential names exist and may request validated writes or
deletions. Secret values never flow back from Jaeger and ARES never resolves a
Jaeger credential path.
"""

from __future__ import annotations

from typing import Any


class RuntimeCredentialError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _require_support() -> None:
    from api.ares_capabilities import capability_contract_for_backend
    from api.backend_catalog import JAEGER_BACKEND_ID

    negotiated = capability_contract_for_backend(JAEGER_BACKEND_ID)
    feature = ((negotiated.get("runtime_contract") or {}).get("features") or {}).get(
        "credentials") or {}
    if negotiated.get("negotiated") is not True or feature.get("available") is not True:
        raise RuntimeCredentialError(
            str(negotiated.get("error") or
                "the selected Jaeger runtime does not advertise credential support"),
            503,
        )


def _query(what: str) -> Any:
    _require_support()
    try:
        from api.providers.jaeger.streaming import query_local_companion

        return query_local_companion(what, {})
    except RuntimeCredentialError:
        raise
    except Exception as exc:
        raise RuntimeCredentialError(f"Jaeger credential query failed: {exc}", 502) from exc


def _command(command: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_support()
    try:
        from api.providers.jaeger.streaming import command_local_companion

        result = command_local_companion(command, args)
    except RuntimeCredentialError:
        raise
    except Exception as exc:
        raise RuntimeCredentialError(f"Jaeger credential command failed: {exc}", 502) from exc
    return result if isinstance(result, dict) else {"ok": True}


def list_runtime_credentials() -> set[str]:
    result = _query("list_credentials")
    if not isinstance(result, dict) or not isinstance(result.get("credentials"), list):
        raise RuntimeCredentialError("Jaeger returned an invalid credential inventory", 502)
    return {str(name) for name in result["credentials"] if str(name).strip()}


def set_runtime_credential(name: str, value: str) -> dict[str, Any]:
    return _command("set_credential", {"name": name, "value": value})


def delete_runtime_credential(name: str) -> dict[str, Any]:
    return _command("delete_credential", {"name": name})


__all__ = [
    "RuntimeCredentialError",
    "delete_runtime_credential",
    "list_runtime_credentials",
    "set_runtime_credential",
]
