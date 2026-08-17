"""Modular FastAPI router registration."""

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.routing import APIRouter

from .adapters import router as adapters_router
from .analytics import router as analytics_router
from .auth import router as auth_router
from .ares import router as ares_router
from .controls import router as controls_router
from .discovery import router as discovery_router
from .env import router as env_router
from .webhooks import router as webhooks_router
from .secrets import router as secrets_router
from .pairing import router as pairing_router
from .backends import router as backends_router
from .email import router as email_router
from .health import router as health_router
from .interactions import router as interactions_router
from .kanban import router as kanban_router
from .caldav import router as caldav_router
from .model_intelligence import router as model_intelligence_router
from .library import router as library_router
from .git import legacy_router as legacy_git_router, router as git_router
from .gateway import router as gateway_router
from .hatchery import router as hatchery_router
from .files import router as files_router
from .file_delivery import router as file_delivery_router
from .models import router as models_router
from .notes import router as notes_router
from .maintenance import router as maintenance_router
from .media import router as media_router
from .memory import router as memory_router
from .mcp import router as mcp_router
from .onboarding import router as onboarding_router
from .profiles import router as profiles_router
from .projects import router as projects_router
from .prompts import router as prompts_router
from .providers import router as providers_router
from .schedules import router as schedules_router
from .realtime import router as realtime_router
from .session import router as session_router
from .settings import router as settings_router
from .shares import router as shares_router
from .si import router as si_router
from .skills import router as skills_router
from .uploads import router as uploads_router
from .workspaces import router as workspaces_router
from .wiki import router as wiki_router
from .research import router as research_router
from .sam_conversation import router as sam_conversation_router
from .journal import router as journal_router
from .readiness import router as readiness_router
from .delegation import router as delegation_router
from .dispatch import router as dispatch_router
from .product_state import router as product_state_router
from .rankings import router as rankings_router
from .jaeger_onboarding import router as jaeger_onboarding_router
from .organizer import router as organizer_router
from .native_system import router as native_system_router
from .companion import router as companion_router
from .content_features import router as content_features_router
from .hermes_compat import router as hermes_compat_router
from .harness import router as harness_router
from .inventory import router as inventory_router


@dataclass(frozen=True)
class RouterRegistration:
    """One controller router registration and its maintenance-facing name."""

    name: str
    router: APIRouter
    legacy: bool = False


# Registration order is part of route precedence. This tuple is the only place
# a controller router is installed; counts and inventory are derived from it.
CORE_ROUTER_REGISTRY = (
    RouterRegistration("harness", harness_router),
    RouterRegistration("providers", providers_router),
    RouterRegistration("adapters", adapters_router),
    RouterRegistration("analytics", analytics_router),
    RouterRegistration("health", health_router),
    RouterRegistration("interactions", interactions_router),
    RouterRegistration("kanban", kanban_router),
    RouterRegistration("caldav", caldav_router),
    RouterRegistration("model_intelligence", model_intelligence_router),
    RouterRegistration("library", library_router),
    RouterRegistration("git", git_router),
    RouterRegistration("legacy_git", legacy_git_router, legacy=True),
    RouterRegistration("gateway", gateway_router),
    RouterRegistration("hatchery", hatchery_router),
    RouterRegistration("files", files_router),
    RouterRegistration("file_delivery", file_delivery_router),
    RouterRegistration("models", models_router),
    RouterRegistration("notes", notes_router),
    RouterRegistration("maintenance", maintenance_router),
    RouterRegistration("media", media_router),
    RouterRegistration("memory", memory_router),
    RouterRegistration("mcp", mcp_router),
    RouterRegistration("auth", auth_router),
    RouterRegistration("controls", controls_router),
    RouterRegistration("discovery", discovery_router),
    RouterRegistration("email", email_router),
    RouterRegistration("ares", ares_router),
    RouterRegistration("secrets", secrets_router),
    RouterRegistration("onboarding", onboarding_router),
    RouterRegistration("profiles", profiles_router),
    RouterRegistration("projects", projects_router),
    RouterRegistration("prompts", prompts_router),
    RouterRegistration("pairing", pairing_router),
    RouterRegistration("schedules", schedules_router),
    RouterRegistration("settings", settings_router),
    RouterRegistration("env", env_router),
    RouterRegistration("shares", shares_router),
    RouterRegistration("si", si_router),
    RouterRegistration("skills", skills_router),
    RouterRegistration("uploads", uploads_router),
    RouterRegistration("session", session_router),
    RouterRegistration("webhooks", webhooks_router),
    RouterRegistration("workspaces", workspaces_router),
    RouterRegistration("wiki", wiki_router),
    RouterRegistration("journal", journal_router),
    RouterRegistration("readiness", readiness_router),
    RouterRegistration("delegation", delegation_router),
    RouterRegistration("dispatch", dispatch_router),
    RouterRegistration("product_state", product_state_router),
    RouterRegistration("rankings", rankings_router),
    RouterRegistration("jaeger_onboarding", jaeger_onboarding_router),
    RouterRegistration("organizer", organizer_router),
    RouterRegistration("native_system", native_system_router),
    RouterRegistration("companion", companion_router),
    RouterRegistration("content_features", content_features_router),
    RouterRegistration("backends", backends_router),
    RouterRegistration("realtime", realtime_router),
    RouterRegistration("research", research_router),
    RouterRegistration("sam_conversation", sam_conversation_router),
    RouterRegistration("inventory", inventory_router),
    RouterRegistration("hermes_compat", hermes_compat_router, legacy=True),
)


def install_core_routers(application: FastAPI) -> None:
    names = [entry.name for entry in CORE_ROUTER_REGISTRY]
    if len(names) != len(set(names)):
        raise RuntimeError("Duplicate controller router name")
    routers = [id(entry.router) for entry in CORE_ROUTER_REGISTRY]
    if len(routers) != len(set(routers)):
        raise RuntimeError("The same controller router was registered more than once")
    for entry in CORE_ROUTER_REGISTRY:
        application.include_router(entry.router)


__all__ = ["CORE_ROUTER_REGISTRY", "RouterRegistration", "install_core_routers"]
