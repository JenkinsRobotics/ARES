"""One-way migration boundary for pre-Jaeger ARES configuration.

Only this module may know predecessor environment names or persisted backend
identifiers. Callers receive canonical Jaeger values and never emit the old
spellings again.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "ARES_JAEGER_SOURCE_DIR": ("ARES_JROS_DIR",),
    "ARES_JAEGER_CONFIG_PATH": ("ARES_JROS_CONFIG_PATH",),
    "ARES_JAEGER_INSTANCE": ("ARES_JROS_INSTANCE",),
}

BACKEND_ID_ALIASES: dict[str, str] = {
    "jaeger": "jaeger_local",
    "jaegerai": "jaeger_local",
    "jaeger_ai": "jaeger_local",
    "jros": "jaeger_local",
    "jros_local": "jaeger_local",
    "hermes": "jaeger_local",
    "hermes_local": "jaeger_local",
}


def environment_value(canonical_name: str, environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    for name in (canonical_name, *_ENV_ALIASES.get(canonical_name, ())):
        value = str(source.get(name) or "").strip()
        if value:
            return value
    return ""


def configured_alias(canonical_name: str, environ: Mapping[str, str] | None = None) -> tuple[str, str] | None:
    source = os.environ if environ is None else environ
    for name in (canonical_name, *_ENV_ALIASES.get(canonical_name, ())):
        value = str(source.get(name) or "").strip()
        if value:
            return name, value
    return None


__all__ = ["BACKEND_ID_ALIASES", "configured_alias", "environment_value"]
