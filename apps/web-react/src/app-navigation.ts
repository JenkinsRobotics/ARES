import { lazy, type ComponentType, type LazyExoticComponent } from "react";
import {
  Activity,
  BookOpen,
  Cable,
  Cpu,
  FolderKanban,
  Gauge,
  GraduationCap,
  MessageCircle,
  Search,
  Server,
  Shield,
  Sparkles,
  Webhook,
  Wrench,
  type LucideIcon,
} from "lucide-react";

const named = <T,>(loader: () => Promise<T>, key: keyof T) =>
  lazy(async () => ({ default: (await loader())[key] as ComponentType }));

/**
 * One pane inside a hub tab.
 *
 * Every view was previously its own top-level route. The `legacy` paths are
 * kept as redirects so existing bookmarks, docs, and deep-links resolve into
 * the hub rather than 404ing through the catch-all.
 */
export type HubView = {
  id: string;
  label: string;
  component: LazyExoticComponent<ComponentType>;
  legacy: string[];
};

/** A primary tab within a hub surface. */
export type HubTab = {
  id: string;
  label: string;
  icon: LucideIcon;
  /** One-line description rendered under the tab bar. */
  blurb: string;
  views: HubView[];
};

export type AppRoute = {
  path: string;
  to: string;
  label: string;
  icon: LucideIcon;
  component: LazyExoticComponent<ComponentType>;
  /**
   * Optional heading this route sits under inside its surface. Surfaces like
   * System hold a dozen destinations; a flat list buries them. Routes with no
   * group render first, ungrouped.
   */
  group?: string;
};

/**
 * The four ARES surfaces.
 *
 * Chat | Knowledge Hub | Control Center | Telemetry & Security
 *
 * Twenty-one standalone micro-routes were folded into these four. Everything
 * that used to be a page is now a tab (or a view inside a tab) so related
 * tools sit next to each other instead of behind separate navigations.
 *
 * Settings is intentionally NOT a fifth surface — it is a utility opened from
 * the bottom-left gear and uses its own sidebar ownership.
 */
export type NavigationSection = {
  id: "chat" | "knowledge" | "control" | "telemetry";
  label: string;
  /** Default deep-link when the rail icon is clicked */
  home: string;
  routes: AppRoute[];
  /** Tabs rendered inside the surface (and mirrored into the sidebar). */
  tabs: HubTab[];
};

/** Deck mode including the non-environment Settings utility. */
export type DeckSurface = NavigationSection["id"] | "settings";

// ── Knowledge Hub ──────────────────────────────────────────────────────────

export const KNOWLEDGE_TABS: HubTab[] = [
  {
    id: "documents",
    label: "Documents",
    icon: BookOpen,
    blurb: "Indexed books, papers, workspace docs, and local markdown.",
    views: [
      {
        id: "documents",
        label: "Documents",
        component: named(() => import("@/features/library/LibraryPage"), "LibraryPage"),
        legacy: ["/library"],
      },
    ],
  },
  {
    id: "collections",
    label: "Collections",
    icon: FolderKanban,
    blurb: "Semantic grouping for RAG vector stores.",
    views: [
      {
        id: "collections",
        label: "Collections",
        component: named(
          () => import("@/features/library/LibraryCollectionsPage"),
          "LibraryCollectionsPage",
        ),
        legacy: ["/collections"],
      },
    ],
  },
  {
    id: "search",
    label: "Semantic Search",
    icon: Search,
    blurb: "Vector + keyword search across every indexed document.",
    views: [
      {
        id: "search",
        label: "Semantic Search",
        component: named(() => import("@/features/library/SearchPage"), "SearchPage"),
        legacy: ["/search"],
      },
    ],
  },
];

// ── Control Center ─────────────────────────────────────────────────────────

export const CONTROL_TABS: HubTab[] = [
  {
    id: "overview",
    label: "Overview",
    icon: Server,
    blurb: "System status at a glance.",
    views: [
      {
        id: "overview",
        label: "Overview",
        component: named(() => import("@/features/system/SystemPage"), "SystemPage"),
        legacy: ["/system"],
      },
    ],
  },
  {
    id: "workers",
    label: "Workers & Adapters",
    icon: Cpu,
    blurb: "Live health, credentials, and connection status for every backend.",
    views: [
      {
        id: "workers",
        label: "Workers",
        component: lazy(() => import("@/features/system/AgentsPage")),
        legacy: ["/agents"],
      },
      {
        id: "connections",
        label: "Connections",
        component: named(() => import("@/features/system/ConnectionsPage"), "ConnectionsPage"),
        legacy: ["/connections", "/channels"],
      },
    ],
  },
  {
    id: "tools",
    label: "MCP & Tools",
    icon: Wrench,
    blurb: "Connected MCP servers, active toolsets, and web search.",
    views: [
      {
        id: "mcp",
        label: "MCP Servers",
        component: lazy(() => import("@/features/system/McpPage")),
        legacy: ["/mcp"],
      },
    ],
  },
  {
    id: "skills",
    label: "Skills",
    icon: GraduationCap,
    blurb: "Installed agent skills and the interactive markdown editor.",
    views: [
      {
        id: "skills",
        label: "Installed",
        component: lazy(() => import("@/features/system/SkillsPage")),
        legacy: ["/skills"],
      },
      {
        id: "studio",
        label: "Skill Studio",
        component: lazy(() => import("@/features/system/SkillStudioPage")),
        legacy: ["/skills-studio"],
      },
    ],
  },
  {
    id: "models",
    label: "Local Models",
    icon: Sparkles,
    blurb: "Local GGUF discovery, Ollama daemon models, and the Hatchery.",
    views: [
      {
        id: "hatchery",
        label: "Local Models",
        component: lazy(() => import("@/features/system/HatcheryPage")),
        legacy: ["/hatchery"],
      },
    ],
  },
];

// ── Telemetry & Security ───────────────────────────────────────────────────

export const TELEMETRY_TABS: HubTab[] = [
  {
    id: "observability",
    label: "Observability & Cost",
    icon: Activity,
    blurb: "Turn logs, token consumption, cost analytics, and latency.",
    views: [
      {
        id: "activity",
        label: "Activity",
        component: named(() => import("@/features/system/ActivityPage"), "ActivityPage"),
        legacy: ["/activity"],
      },
      {
        id: "analytics",
        label: "Analytics",
        component: named(() => import("@/features/system/AnalyticsPage"), "AnalyticsPage"),
        legacy: ["/analytics"],
      },
      {
        id: "usage",
        label: "Usage & cost",
        component: named(() => import("@/features/system/UsageCostPage"), "UsageCostPage"),
        legacy: ["/usage"],
      },
    ],
  },
  {
    id: "security",
    label: "Security & Secrets",
    icon: Shield,
    blurb: "API key vault, retention, redaction rules, and autonomy levels.",
    views: [
      {
        id: "secrets",
        label: "Secrets",
        component: lazy(() => import("@/features/system/SecretsPage")),
        legacy: ["/secrets"],
      },
      {
        id: "memory",
        label: "Memory & Privacy",
        component: named(() => import("@/features/system/MemoryPrivacyPage"), "MemoryPrivacyPage"),
        legacy: ["/memory-privacy"],
      },
      {
        id: "permissions",
        label: "Permissions & Autonomy",
        component: named(
          () => import("@/features/system/PermissionsAutonomyPage"),
          "PermissionsAutonomyPage",
        ),
        legacy: ["/permissions-autonomy"],
      },
    ],
  },
  {
    id: "automations",
    label: "Automations & Daemon",
    icon: Webhook,
    blurb: "Webhook endpoints, device pairing, and daemon configuration.",
    views: [
      {
        id: "webhooks",
        label: "Webhooks",
        component: lazy(() => import("@/features/system/WebhooksPage")),
        legacy: ["/webhooks"],
      },
      {
        id: "pairing",
        label: "Pairing",
        component: lazy(() => import("@/features/system/PairingPage")),
        legacy: ["/pairing"],
      },
      {
        id: "config",
        label: "Advanced settings",
        component: lazy(() => import("@/features/system/ConfigPage")),
        legacy: ["/config"],
      },
    ],
  },
];

export const navigationSections: NavigationSection[] = [
  {
    id: "chat",
    label: "Chat",
    home: "/chat",
    tabs: [],
    routes: [
      {
        path: "chat",
        to: "/chat",
        label: "Sessions",
        icon: MessageCircle,
        component: named(() => import("@/features/chat/ConversationPage"), "ConversationPage"),
      },
      // Legacy alias — same console (bookmarks /session links)
      {
        path: "conversation",
        to: "/conversation",
        label: "Conversation (legacy)",
        icon: MessageCircle,
        component: named(() => import("@/features/chat/ConversationPage"), "ConversationPage"),
      },
    ],
  },
  {
    id: "knowledge",
    label: "Knowledge Hub",
    home: "/knowledge",
    tabs: KNOWLEDGE_TABS,
    routes: [
      {
        path: "knowledge",
        to: "/knowledge",
        label: "Knowledge Hub",
        icon: BookOpen,
        component: named(() => import("@/features/hubs/KnowledgeHubPage"), "KnowledgeHubPage"),
      },
    ],
  },
  {
    id: "control",
    label: "Control Center",
    home: "/control",
    tabs: CONTROL_TABS,
    routes: [
      {
        path: "control",
        to: "/control",
        label: "Control Center",
        icon: Server,
        component: named(() => import("@/features/hubs/ControlCenterPage"), "ControlCenterPage"),
      },
    ],
  },
  {
    id: "telemetry",
    label: "Telemetry & Security",
    home: "/telemetry",
    tabs: TELEMETRY_TABS,
    routes: [
      {
        path: "telemetry",
        to: "/telemetry",
        label: "Telemetry & Security",
        icon: Gauge,
        component: named(() => import("@/features/hubs/TelemetryPage"), "TelemetryPage"),
      },
    ],
  },
];

/** Deep-link for a hub tab/view pair. */
export function hubLink(home: string, tabId: string, viewId?: string): string {
  const base = `${home}?tab=${encodeURIComponent(tabId)}`;
  return viewId ? `${base}&view=${encodeURIComponent(viewId)}` : base;
}

/**
 * Legacy standalone path → its new hub deep-link.
 *
 * Derived from the tab definitions so a view can never drift from its
 * redirect. Consumed by the router to keep every historical URL working.
 */
export const legacyRouteRedirects: Record<string, string> = Object.fromEntries(
  navigationSections.flatMap((section) =>
    section.tabs.flatMap((tab) =>
      tab.views.flatMap((view) =>
        view.legacy.map((path) => [path, hubLink(section.home, tab.id, view.id)] as const),
      ),
    ),
  ),
);

/**
 * Resolve which left-deck surface owns a pathname.
 * `/settings` is never a surface — it is a standalone utility.
 */
export function sectionForPath(pathname: string): DeckSurface {
  // Strip query/hash so accidental full URLs still resolve correctly.
  const path = pathname.split(/[?#]/, 1)[0] || pathname;

  if (path === "/settings" || path.startsWith("/settings/")) {
    return "settings";
  }
  if (path.startsWith("/chat") || path.startsWith("/conversation")) {
    return "chat";
  }
  // Prefer longest matching route prefix so /control wins over accidental shorts.
  let best: { id: NavigationSection["id"]; len: number } | null = null;
  const consider = (id: NavigationSection["id"], candidate: string) => {
    if (path === candidate || path.startsWith(`${candidate}/`)) {
      if (!best || candidate.length > best.len) best = { id, len: candidate.length };
    }
  };
  for (const section of navigationSections) {
    for (const route of section.routes) consider(section.id, route.to);
    consider(section.id, section.home);
    // Legacy paths still highlight their new owner during the redirect tick.
    for (const tab of section.tabs) {
      for (const view of tab.views) {
        for (const legacy of view.legacy) consider(section.id, legacy);
      }
    }
  }
  return best ? (best as { id: NavigationSection["id"] }).id : "chat";
}

/**
 * Router registrations — unique paths. First declaration wins if duplicated.
 */
export const workspaceRoutes = Array.from(
  new Map(
    navigationSections.flatMap((section) => section.routes).map((route) => [route.path, route]),
  ).values(),
);
