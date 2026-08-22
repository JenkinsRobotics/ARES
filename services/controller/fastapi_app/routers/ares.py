"""ARES identity, companion presentation, backend, and device contracts."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ..adapters import AdapterError, AdapterRegistry
from ..dependencies import get_adapter_registry
from ..errors import CoreApiError
from ..request_context import RequestIdentity, profile_scope, require_identity, require_mutation_identity
from .onboarding import require_onboarding_mutation


logger = logging.getLogger(__name__)

router = APIRouter(tags=["ares"])


@router.get("/api/personalities")
def personalities(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.config import get_config, reload_config

    reload_config()
    raw = (get_config().get("agent") or {}).get("personalities") or {}
    items = []
    if isinstance(raw, dict):
        for name, value in raw.items():
            description = ""
            if isinstance(value, dict):
                description = str(value.get("description") or "")
            elif isinstance(value, str):
                # Full text, same as the dict branch — clipping to an arbitrary
                # width is the UI's call, not the API's (silent truncation).
                description = value
            items.append({"name": name, "description": description})
    return {"personalities": items}


@router.post("/api/personality/set")
def set_session_personality(
    payload: dict[str, Any],
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.config import _get_session_agent_lock, get_config, reload_config
    from api.models import get_session

    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise CoreApiError(400, "session_id is required")
    if "name" not in payload:
        raise CoreApiError(400, "Missing required field: name")
    name = str(payload.get("name") or "").strip()
    with profile_scope(identity.profile):
        try:
            session = get_session(session_id)
        except KeyError as exc:
            raise CoreApiError(404, "Session not found") from exc
        if getattr(session, "read_only", False) or getattr(session, "is_subagent", False):
            raise CoreApiError(400, "Subagent sessions are view-only and cannot be modified from WebUI")
        prompt = ""
        if name:
            reload_config()
            personalities = (get_config().get("agent") or {}).get("personalities") or {}
            if not isinstance(personalities, dict) or name not in personalities:
                raise CoreApiError(404, f'Personality "{name}" not found in config.yaml')
            value = personalities[name]
            if isinstance(value, dict):
                parts = [value.get("system_prompt") or value.get("prompt") or ""]
                if value.get("tone"):
                    parts.append(f"Tone: {value['tone']}")
                if value.get("style"):
                    parts.append(f"Style: {value['style']}")
                prompt = "\n".join(part for part in parts if part)
            else:
                prompt = str(value)
        with _get_session_agent_lock(session_id):
            session.personality = name or None
            session.save()
    return {"ok": True, "personality": session.personality, "prompt": prompt}


@router.get("/api/ares/personas")
def personas(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.persona import list_personas

    try:
        return {"personas": list_personas()}
    except Exception as exc:
        raise CoreApiError(400, f"Failed to list personas: {exc}") from exc


@router.get("/api/ares/characters")
def characters(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.characters import list_characters

    try:
        return {"characters": list_characters()}
    except Exception as exc:
        raise CoreApiError(400, f"Failed to list characters: {exc}") from exc


@router.get("/api/ares/character")
def character(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
    id: str = Query(min_length=1, max_length=256),
):
    from api.characters import get_character

    try:
        result = get_character(id)
    except Exception as exc:
        raise CoreApiError(400, f"Failed to load character: {exc}") from exc
    if result is None:
        raise CoreApiError(404, "Character not found")
    return {"character": result}


@router.get("/api/ares/persona/current")
def current_persona(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.config import get_config

    return {"persona_id": str(get_config().get("ares_persona") or "").strip()}


def save_config_values(values: dict[str, Any]) -> None:
    """Persist controller-level runtime choices and reload active config."""
    from api.config import (
        _get_config_path,
        _load_yaml_config_file,
        _save_yaml_config_file,
        reload_config,
    )

    path = _get_config_path()
    config = _load_yaml_config_file(path)
    config.update(values)
    _save_yaml_config_file(path, config)
    reload_config()


@router.get("/api/ares/persona/set")
@router.post("/api/ares/persona/set")
def set_persona(
    payload: dict[str, Any],
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    persona_id = str(payload.get("persona_id") or "").strip()
    try:
        with profile_scope(identity.profile):
            save_config_values({"ares_persona": persona_id})
            if persona_id:
                from api.providers.jaeger.companion_control import update_companion

                update_companion(character_id=persona_id)
    except Exception as exc:
        raise CoreApiError(400, f"Failed to save persona: {exc}") from exc
    return {"ok": True, "persona_id": persona_id}


def _session(session_id: str):
    from api.models import get_session

    try:
        return get_session(session_id)
    except KeyError as exc:
        raise CoreApiError(404, "Session not found") from exc


@router.get("/api/ares/directives")
def get_directives(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    """Standing user directives injected into every worker turn."""
    from api.ares_directives import directives_summary, read_directives_file

    state = read_directives_file()
    summary = directives_summary()
    return {
        "directives": list(state.get("directives") or []),
        "enabled": summary["enabled"],
        "count": summary["active_count"],
        "stored_count": summary["stored_count"],
        "path": summary["path"],
        "scope": summary["scope"],
        "note": summary["note"],
    }


@router.post("/api/ares/directives/set")
def set_directives(
    payload: dict[str, Any],
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    """Replace the stored directives. Omitting ``enabled`` leaves them on."""
    from api.ares_directives import MAX_DIRECTIVES, directives_summary, save_directives

    raw = payload.get("directives", [])
    if raw is not None and not isinstance(raw, (list, str)):
        raise CoreApiError(400, "directives must be a list of strings")
    if isinstance(raw, list) and len(raw) > MAX_DIRECTIVES:
        raise CoreApiError(400, f"At most {MAX_DIRECTIVES} directives are supported")

    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise CoreApiError(400, "enabled must be a boolean")

    try:
        stored = save_directives(raw, enabled=enabled)
    except OSError as exc:
        raise CoreApiError(500, f"Could not save directives: {exc}") from exc

    summary = directives_summary()
    return {
        "ok": True,
        "directives": stored["directives"],
        "enabled": stored["enabled"],
        "count": summary["active_count"],
        "path": summary["path"],
        "note": summary["note"],
    }


@router.get("/api/ares/backend")
def backend(
    identity: Annotated[RequestIdentity, Depends(require_identity)],
    registry: Annotated[AdapterRegistry, Depends(get_adapter_registry)],
    session_id: str = Query(default="", max_length=256),
):
    from api.ares_capabilities import capability_contract_for_backend
    from api.backend_selector import get_active_backend, get_session_backend
    from api.config import get_config

    with profile_scope(identity.profile):
        config = get_config()
        default_backend = get_active_backend(config)
        current = default_backend
        scope = "default"
        if session_id:
            current = get_session_backend(_session(session_id), config)
            scope = "session"
        records = registry.connection_records(profile=identity.profile)
        status = {
            item["id"]: bool((item.get("health") or {}).get("available"))
            for item in records.get("connections") or []
            if item.get("kind") == "runtime"
        }
        capability_contract = capability_contract_for_backend(current)
        return {
            "current": current,
            "default": default_backend,
            "scope": scope,
            "session_id": session_id or None,
            "status": status,
            "capabilities": capability_contract["capabilities"],
            "capability_negotiated": capability_contract["negotiated"],
            "capability_source": capability_contract["source"],
            "capability_error": capability_contract["error"],
            "capability_domains": capability_contract["domains"],
            "capability_ownership": capability_contract["ownership"],
            "capability_features": capability_contract["features"],
            "runtime_contract_version": (
                (capability_contract.get("runtime_contract") or {}).get("contract_version")
            ),
        }


@router.post("/api/ares/backend/set")
def set_backend(
    payload: dict[str, Any],
    identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
    registry: Annotated[AdapterRegistry, Depends(get_adapter_registry)],
):
    from api.ares_capabilities import capabilities_for_backend

    requested = str(payload.get("backend") or "").strip().lower()
    if requested in {"", "none", "unassigned"}:
        session_id = str(payload.get("session_id") or "").strip()
        with profile_scope(identity.profile):
            if session_id:
                session = _session(session_id)
                session.ares_backend = ""
                session.save(touch_updated_at=False)
                return {
                    "ok": True,
                    "backend": "",
                    "scope": "session",
                    "session_id": session_id,
                    "capabilities": [],
                }
            save_config_values({"ares_backend": ""})
        return {"ok": True, "backend": "", "scope": "default", "capabilities": []}
    try:
        backend_name = registry.execution_adapter(requested).adapter_id
        health = registry.test_connection(backend_name, profile=identity.profile)
    except AdapterError as exc:
        raise CoreApiError(
            exc.status_code,
            exc.message,
            code=exc.code,
            context=exc.context,
        ) from exc
    if not health.get("ok"):
        message = str((health.get("health") or {}).get("message") or "The runtime is unavailable.")
        raise CoreApiError(409, f"{backend_name} cannot be selected: {message}", code="runtime_unavailable")
    session_id = str(payload.get("session_id") or "").strip()
    with profile_scope(identity.profile):
        if session_id:
            session = _session(session_id)
            session.ares_backend = backend_name
            session.save(touch_updated_at=False)
            return {
                "ok": True,
                "backend": backend_name,
                "scope": "session",
                "session_id": session_id,
                "capabilities": capabilities_for_backend(backend_name),
            }
        save_config_values({"ares_backend": backend_name})
    from api.provider_registry import (
        ProviderRegistryCorrupt,
        load_provider_registry,
        save_provider,
    )

    existing = load_provider_registry().get("providers", {}).get(backend_name, {})
    try:
        save_provider(backend_name, {
            **existing,
            "enabled": True,
            "kind": "runtime",
            "capabilities": capabilities_for_backend(backend_name),
            "metadata": {
                **(existing.get("metadata", {}) if isinstance(existing, dict) else {}),
                "selected_by": "operator",
            },
        })
    except ProviderRegistryCorrupt:
        # The selection itself already succeeded above (ares_backend is saved to
        # config); this registry entry is bookkeeping. Failing the request here
        # would report an error for a change that did take effect, so log and
        # carry on rather than block the user from choosing a provider.
        logger.warning(
            "Provider registry could not be read; %s was selected but its "
            "registry entry was not updated.",
            backend_name,
            exc_info=True,
        )
    return {
        "ok": True,
        "backend": backend_name,
        "scope": "default",
        "capabilities": capabilities_for_backend(backend_name),
    }


@router.get("/api/ares/providers")
def providers(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    """Return operator-configured external connections; never secrets."""
    from api.provider_registry import load_provider_registry

    return load_provider_registry()


@router.put("/api/ares/providers/{provider_id}")
def put_provider(
    provider_id: str,
    payload: dict[str, Any],
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.provider_registry import ProviderRegistryCorrupt, save_provider

    try:
        provider = save_provider(provider_id, payload)
    except ProviderRegistryCorrupt as exc:
        # Refusing the write is the point: the file could not be read, so
        # saving would replace every other configured provider with nothing.
        raise CoreApiError(
            409,
            "The provider registry file could not be read, so it was not "
            f"overwritten. Repair or remove {exc.path} and try again.",
            code="provider_registry_corrupt",
        ) from exc
    except ValueError as exc:
        raise CoreApiError(400, str(exc), code="invalid_provider_connection") from exc
    return {"ok": True, "provider": provider}


@router.delete("/api/ares/providers/{provider_id}")
def delete_provider(
    provider_id: str,
    _identity: Annotated[RequestIdentity, Depends(require_mutation_identity)],
):
    from api.provider_registry import ProviderRegistryCorrupt, remove_provider

    try:
        removed = remove_provider(provider_id)
    except ProviderRegistryCorrupt as exc:
        raise CoreApiError(
            409,
            "The provider registry file could not be read, so it was not "
            f"overwritten. Repair or remove {exc.path} and try again.",
            code="provider_registry_corrupt",
        ) from exc
    return {"ok": True, "removed": removed}


@router.get("/api/ares/self-persistence")
def self_persistence(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.ares_self_persistence import build_self_persistence_contract
    from api.config import get_config

    return {"self_persistence": build_self_persistence_contract(get_config())}


@router.get("/api/ares/runtime-context")
def runtime_context(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.ares_runtime_context import build_runtime_context
    from api.backend_selector import get_active_backend
    from api.config import get_config

    config = get_config()
    return {"runtime_context": build_runtime_context(backend=get_active_backend(config))}


@router.get("/api/ares/tools")
def tools(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.ares_tool_adapter import register_ares_tools

    # This is a JSON discovery contract, not an executable in-process JaegerAI
    # registry. MCP-shaped schemas contain no Python classes or callables and
    # are therefore safe to serialize regardless of the active runtime.
    return {"tools": register_ares_tools(target="mcp")}


@router.get("/api/ares/identity")
def identity(
    request_identity: Annotated[RequestIdentity, Depends(require_identity)],
    session_id: str = Query(default="", max_length=256),
):
    from api.ares_identity import build_identity_payload
    from api.backend_selector import get_active_backend, get_session_backend
    from api.config import get_config, load_settings
    from api.profiles import get_active_profile_name

    with profile_scope(request_identity.profile):
        config = get_config()
        backend_name = get_active_backend(config)
        if session_id:
            backend_name = get_session_backend(_session(session_id), config)
        persona_id = str(config.get("ares_persona") or "").strip() or None
        bot_name = str((load_settings() or {}).get("bot_name") or "").strip() or None
        return build_identity_payload(
            profile=get_active_profile_name(),
            bot_name=bot_name,
            backend=backend_name,
            persona_id=persona_id,
        )


@router.get("/api/ares/device/status")
def device_status(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.ares_devices import device_status as status
    from api.config import get_config

    return status(get_config())


@router.get("/api/ares/devices")
def devices(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    from api.ares_devices import device_status as status, load_registry
    from api.config import get_config

    config = get_config()
    return {"current": status(config), "registry": load_registry(config)}


@router.get("/api/ares/adapters")
def legacy_adapters(_identity: Annotated[RequestIdentity, Depends(require_identity)]):
    """Legacy adapter inventory retained beside the neutral connections API."""
    from api.backends.router import get_router

    try:
        # Inventory lists every registered adapter with an availability flag;
        # using only the available set silently hid unavailable runtimes.
        backends = get_router().list_all()
    except Exception as exc:
        raise CoreApiError(400, f"Failed to list ARES adapters: {exc}") from exc

    inventory = {}
    for name, backend in backends.items():
        try:
            label = backend.get_backend_name()
        except Exception:
            label = str(getattr(backend, "display_label", "") or name)
        try:
            inventory[name] = {
                "available": backend.is_available(),
                "label": label,
                "health": backend.health(),
                "identity_projection": backend.identity_projection(),
                "capabilities": backend.capabilities(),
                "chat_session_support": backend.chat_session_support(),
                "tools": backend.tools(),
                "settings_schema": backend.settings_schema(),
            }
        except Exception as exc:
            # Optional runtimes may be only partly configured. One broken probe
            # must not make the entire Connections inventory unavailable.
            inventory[name] = {
                "available": False,
                "label": label,
                "health": {
                    "status": "degraded",
                    "latency_ms": 0.0,
                    "message": str(exc),
                },
                "identity_projection": {
                    "name": label,
                    "description": "Optional runtime is not fully configured.",
                    "avatar_state": "idle",
                },
                "capabilities": {},
                "chat_session_support": {},
                "tools": [],
                "settings_schema": {"type": "object", "properties": {}},
            }
    return inventory


@router.get("/api/ares/approvals/pending")
def all_pending_approvals(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    from api.route_approvals import _lock, _pending

    approvals = []
    with _lock:
        for session_id, entries in _pending.items():
            for entry in entries if isinstance(entries, list) else []:
                approvals.append(
                    {
                        "session_id": session_id,
                        "approval_id": entry.get("approval_id"),
                        "command": entry.get("command") or entry.get("message") or "",
                        "type": entry.get("type") or "tool",
                        "created_at": entry.get("created_at") or "",
                        "tool_name": entry.get("tool_name") or entry.get("name") or "",
                    }
                )
    return {"approvals": approvals}


@router.get("/api/ares/audit/logs")
def audit_logs(
    _identity: Annotated[RequestIdentity, Depends(require_identity)],
):
    import json

    from api.paths import HOME

    records = []
    audit_file = HOME / ".ares" / "audit.log"
    try:
        if audit_file.is_file():
            with audit_file.open("r", encoding="utf-8") as source:
                for line in source:
                    try:
                        record = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(record, dict):
                        records.append(record)
    except OSError as exc:
        raise CoreApiError(400, f"Failed to fetch audit logs: {exc}") from exc
    return {"logs": records[-100:]}


@router.post("/api/ares/device/configure")
def configure_device(
    payload: dict[str, Any],
    identity: Annotated[RequestIdentity, Depends(require_onboarding_mutation)],
):
    from api.ares_devices import device_status as status, normalize_config_update, register_device
    from api.config import get_config

    with profile_scope(identity.profile):
        updates = normalize_config_update(payload, get_config())
        save_config_values(updates)
        config = get_config()
        registration = register_device(config=config)
    return {"ok": True, "updates": updates, "status": status(config), "registration": registration}


@router.post("/api/ares/device/register")
def register_device(
    payload: dict[str, Any],
    identity: Annotated[RequestIdentity, Depends(require_onboarding_mutation)],
):
    from api.ares_devices import register_device as register
    from api.config import get_config

    record = payload.get("device")
    with profile_scope(identity.profile):
        return register(record if isinstance(record, dict) else None, get_config())






@router.get("/api/ares/rag-sources")
def get_rag_sources():
    """Get configured RAG document sources."""
    from pathlib import Path
    import yaml
    
    config_path = Path.home() / ".ares" / "rag_sources.yaml"
    if not config_path.exists():
        return {"sources": [], "enabled": False}
    
    try:
        config = yaml.safe_load(config_path.read_text()) or {}
        return {
            "sources": config.get("sources", []),
            "enabled": config.get("enabled", False),
            "embedding_model": config.get("embedding_model"),
            "embedding_dims": config.get("embedding_dims"),
        }
    except Exception as e:
        return {"error": str(e), "sources": [], "enabled": False}


@router.post("/api/ares/rag-sources/set")
def set_rag_sources(request: dict):
    """Set RAG document sources configuration."""
    from pathlib import Path
    import yaml
    import time
    
    config_path = Path.home() / ".ares" / "rag_sources.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    sources = request.get("sources", [])
    enabled = request.get("enabled", True)
    embedding_model = request.get("embedding_model", "nomic-embed-text")
    
    config = {
        "sources": sources,
        "enabled": enabled,
        "embedding_model": embedding_model,
        "embedding_dims": 768,
        "updated_at": time.time(),
    }
    
    config_path.write_text(yaml.dump(config, default_flow_style=False))
    
    return {"ok": True, "count": len(sources)}


@router.post("/api/ares/rag-sources/add-folder")
def add_rag_folder(request: dict):
    """Add a folder path to configured RAG/knowledge sources."""
    from pathlib import Path
    import yaml
    import time

    folder_path = (request.get("path") or "").strip()
    if not folder_path:
        raise CoreApiError(400, "Missing 'path' parameter.", code="invalid_param")

    p = Path(folder_path).expanduser()
    if not p.exists():
        raise CoreApiError(404, f"Path '{folder_path}' does not exist.", code="path_not_found")

    config_path = Path.home() / ".ares" / "rag_sources.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if config_path.exists():
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            config = {}

    sources = config.get("sources", [])
    existing_paths = {
        (s.get("path") if isinstance(s, dict) else str(s))
        for s in sources
    }

    if str(p) not in existing_paths:
        sources.append({"path": str(p), "enabled": True})

    config["sources"] = sources
    config["enabled"] = True
    config["updated_at"] = time.time()
    config_path.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")

    return {"ok": True, "path": str(p), "total_sources": len(sources)}


@router.post("/api/ares/rag-sources/remove-folder")
def remove_rag_folder(request: dict):
    """Remove a folder path from configured RAG/knowledge sources."""
    from pathlib import Path
    import yaml
    import time

    folder_path = (request.get("path") or "").strip()
    if not folder_path:
        raise CoreApiError(400, "Missing 'path' parameter.", code="invalid_param")

    config_path = Path.home() / ".ares" / "rag_sources.yaml"
    if not config_path.exists():
        return {"ok": True, "total_sources": 0}

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        config = {}

    sources = config.get("sources", [])
    updated = [
        s for s in sources
        if (s.get("path") if isinstance(s, dict) else str(s)) != folder_path
        and (s.get("path") if isinstance(s, dict) else str(s)) != str(Path(folder_path).expanduser())
    ]

    config["sources"] = updated
    config["updated_at"] = time.time()
    config_path.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")

    return {"ok": True, "path": folder_path, "total_sources": len(updated)}


@router.get("/api/knowledge/graph")
def get_knowledge_graph(
    max_nodes: int = 500,
    query: str | None = None,
    tag: str | None = None,
    cluster: str | None = None,
):
    """Get the interactive knowledge graph for the ARES Memory Tab."""
    from api.knowledge_graph import build_knowledge_graph
    try:
        return build_knowledge_graph(
            max_nodes=max_nodes,
            query=query,
            tag=tag,
            cluster=cluster,
        )
    except Exception as exc:
        logger.error("Failed building knowledge graph: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc), "nodes": [], "links": []}


@router.get("/api/knowledge/document")
def get_knowledge_document(path: str):
    """Read a specific document's content for node inspection."""
    from api.knowledge_graph import read_knowledge_document
    return read_knowledge_document(path)


@router.post("/api/ares/rag-sources/scan")
def scan_rag_sources(_identity: Annotated[RequestIdentity, Depends(require_mutation_identity)]):
    """Index every configured RAG source into keyword search and, when the
    vector store is usable, semantic search.

    The two indexes fail independently and are reported independently: keyword
    search needs only SQLite, while the vector half additionally needs
    ``sqlite-vec`` plus a reachable embeddings endpoint. Collapsing them into
    one number is how a scan that embedded nothing still reads as a success.
    """
    from pathlib import Path

    import yaml

    from api.context_store import is_enabled, reindex_source, store_status
    from api.journal.import_documents import scan_documents

    config_path = Path.home() / ".ares" / "rag_sources.yaml"
    if not config_path.exists():
        raise CoreApiError(
            400,
            "No RAG sources are configured.",
            code="rag_sources_missing",
            context={
                "reason": f"{config_path} does not exist.",
                "fix": "POST /api/ares/rag-sources/set with a sources list.",
            },
        )

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise CoreApiError(
            400,
            "RAG source configuration could not be read.",
            code="rag_sources_unparsable",
            context={"reason": str(exc), "fix": f"Fix the YAML in {config_path}."},
        ) from exc

    if not config.get("enabled"):
        return {"documents_indexed": 0, "chunks_embedded": 0, "results": [], "note": "RAG sources are disabled."}

    from api.config import get_config

    app_config = get_config()
    vector_ready = bool(is_enabled(app_config)) and bool(store_status().get("available"))

    results: list[dict[str, Any]] = []
    documents_indexed = 0
    chunks_embedded = 0

    for source in config.get("sources") or []:
        raw_path = str((source or {}).get("path") or "").strip()
        if not raw_path:
            continue
        source_path = Path(raw_path).expanduser()
        if not source_path.exists():
            results.append({"path": raw_path, "status": "not_found"})
            continue

        wanted = [str(t).lower() for t in (source.get("index") or ["fts", "vector"])]
        include = [str(p) for p in (source.get("include") or [])]

        try:
            stats = scan_documents(scan_paths=[source_path], include_globs=include or None)
        except Exception as exc:
            results.append({"path": raw_path, "status": "error", "error": str(exc)})
            continue

        imported = int(stats.get("imported") or 0)
        documents_indexed += imported
        entry: dict[str, Any] = {
            "path": raw_path,
            "status": "indexed",
            "documents": imported,
            "skipped": int(stats.get("skipped") or 0),
            "errored": int(stats.get("errored") or 0),
            "keyword_index": True,
        }

        if "vector" not in wanted:
            entry["vector_index"] = "not_requested"
        elif not vector_ready:
            # Say which half did not happen instead of implying both ran.
            entry["vector_index"] = "unavailable"
            entry["vector_reason"] = str(store_status().get("reason") or "vector store is disabled")
        else:
            embedded = 0
            for record in _scanned_documents(source_path):
                if reindex_source(
                    f"rag:{record['path']}",
                    "rag_document",
                    record["path"],
                    record["content"],
                    config_data=app_config,
                    mtime=record.get("mtime"),
                ):
                    embedded += 1
            chunks_embedded += embedded
            entry["vector_index"] = True
            entry["documents_embedded"] = embedded

        results.append(entry)

    return {
        "documents_indexed": documents_indexed,
        "chunks_embedded": chunks_embedded,
        "vector_available": vector_ready,
        "results": results,
    }


def _scanned_documents(root) -> list[dict[str, Any]]:
    """Documents the journal holds for ``root``, for vector re-indexing.

    Read back from the journal rather than re-walking the filesystem so the
    vector index covers exactly what keyword search covers — the two halves
    cannot silently drift onto different file sets.
    """
    from api.journal.schema import get_db

    prefix = f"{str(root).rstrip('/')}/%"
    try:
        rows = get_db().execute(
            "SELECT file_path, content, created_at FROM documents WHERE file_path LIKE ?",
            (prefix,),
        ).fetchall()
    except Exception:
        logger.debug("Could not read scanned documents for %s", root, exc_info=True)
        return []
    return [
        {"path": row[0], "content": row[1] or "", "mtime": row[2]}
        for row in rows
        if (row[1] or "").strip()
    ]


@router.post("/api/ares/provider/sync")
def sync_provider_configuration(
    payload: dict[str, Any],
    identity: Annotated[RequestIdentity, Depends(require_onboarding_mutation)],
):
    from api.ares_provider_sync import sync_fallback_chain, sync_provider
    from api.config import _get_config_path

    targets = payload.get("targets") or ["ares", "jaeger"]
    if not isinstance(targets, list):
        raise CoreApiError(400, "targets must be a list of ares and/or jaeger")
    dry_run = bool(payload.get("dry_run", False))
    try:
        with profile_scope(identity.profile):
            config_path = _get_config_path()
            result = sync_provider(
                provider=str(payload.get("provider") or "").strip(),
                model=str(payload.get("model") or "").strip(),
                base_url=str(payload.get("base_url") or "").strip() or None,
                targets=targets,
                api_key_env=str(payload.get("api_key_env") or "").strip() or None,
                ares_config_path=config_path,
                dry_run=dry_run,
            )
            if "jaeger" in targets:
                try:
                    result["fallback_chain"] = sync_fallback_chain(
                        ares_config_path=config_path,
                        dry_run=dry_run,
                    )
                except Exception as exc:
                    result["fallback_chain"] = {"ok": False, "error": str(exc)}
    except ValueError as exc:
        raise CoreApiError(400, str(exc)) from exc
    except Exception as exc:
        raise CoreApiError(400, f"Failed to sync provider: {exc}") from exc
    return result


__all__ = ["router"]
