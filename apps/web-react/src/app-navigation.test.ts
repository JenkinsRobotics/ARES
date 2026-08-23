import { describe, expect, it } from "vitest";

import {
  CONTROL_TABS,
  KNOWLEDGE_TABS,
  TELEMETRY_TABS,
  hubLink,
  legacyRouteRedirects,
  navigationSections,
  sectionForPath,
  workspaceRoutes,
} from "@/app-navigation";
import {
  normalizeSettingsSection,
  SETTINGS_SECTIONS,
} from "@/features/settings/constants";

/** Every view across every surface, flattened. */
const allViews = navigationSections.flatMap((section) =>
  section.tabs.flatMap((tab) => tab.views.map((view) => ({ section, tab, view }))),
);

describe("app navigation registry", () => {
  it("exposes exactly four surfaces (Settings is not a fifth)", () => {
    expect(navigationSections.map((section) => section.id)).toEqual([
      "chat",
      "knowledge",
      "control",
      "telemetry",
    ]);
    expect(navigationSections.map((section) => section.label)).toEqual([
      "Chat",
      "Knowledge Hub",
      "Control Center",
      "Telemetry & Security",
    ]);
    expect(navigationSections.some((s) => s.id === ("settings" as never))).toBe(false);
    expect(workspaceRoutes.find((r) => r.path === "settings")).toBeUndefined();
  });

  it("registers one route per surface, plus the legacy chat alias", () => {
    expect(workspaceRoutes.map((route) => route.path)).toEqual([
      "chat",
      "conversation",
      "knowledge",
      "control",
      "telemetry",
    ]);
    expect(new Set(workspaceRoutes.map((route) => route.path)).size).toBe(workspaceRoutes.length);
    expect(new Set(workspaceRoutes.map((route) => route.to)).size).toBe(workspaceRoutes.length);
    for (const route of workspaceRoutes) {
      expect(route.to).toBe(`/${route.path}`);
      expect(route.label.length).toBeGreaterThan(0);
      expect(route.component).toBeTypeOf("object");
    }
  });

  it("keeps every destination from the 21 legacy routes", () => {
    // The pre-consolidation registry had 21 routes: chat + conversation and 19
    // standalone pages. Each of those 19 must survive as a hub view.
    expect(allViews).toHaveLength(19);
    const labels = allViews.map(({ view }) => view.label);
    expect(labels).toEqual(
      expect.arrayContaining([
        "Documents",
        "Collections",
        "Semantic Search",
        "Overview",
        "Workers",
        "Connections",
        "MCP Servers",
        "Installed",
        "Skill Studio",
        "Local Models",
        "Activity",
        "Analytics",
        "Usage & cost",
        "Secrets",
        "Memory & Privacy",
        "Permissions & Autonomy",
        "Webhooks",
        "Pairing",
        "Advanced settings",
      ]),
    );
  });

  it("gives each hub the tabs the layout calls for", () => {
    expect(KNOWLEDGE_TABS.map((t) => t.id)).toEqual(["documents", "collections", "search"]);
    expect(CONTROL_TABS.map((t) => t.id)).toEqual([
      "overview",
      "workers",
      "tools",
      "skills",
      "models",
    ]);
    expect(TELEMETRY_TABS.map((t) => t.id)).toEqual([
      "observability",
      "security",
      "automations",
    ]);
    for (const tab of [...KNOWLEDGE_TABS, ...CONTROL_TABS, ...TELEMETRY_TABS]) {
      expect(tab.views.length).toBeGreaterThan(0);
      expect(tab.blurb.length).toBeGreaterThan(0);
      for (const view of tab.views) {
        expect(view.component).toBeTypeOf("object");
      }
    }
  });

  it("keeps tab and view ids unique within their scope", () => {
    for (const section of navigationSections) {
      const tabIds = section.tabs.map((t) => t.id);
      expect(new Set(tabIds).size).toBe(tabIds.length);
      for (const tab of section.tabs) {
        const viewIds = tab.views.map((v) => v.id);
        expect(new Set(viewIds).size).toBe(viewIds.length);
      }
    }
  });
});

describe("legacy redirects", () => {
  it("maps every old standalone path to its new hub deep-link", () => {
    expect(legacyRouteRedirects["/library"]).toBe("/knowledge?tab=documents&view=documents");
    expect(legacyRouteRedirects["/collections"]).toBe("/knowledge?tab=collections&view=collections");
    expect(legacyRouteRedirects["/search"]).toBe("/knowledge?tab=search&view=search");
    expect(legacyRouteRedirects["/system"]).toBe("/control?tab=overview&view=overview");
    expect(legacyRouteRedirects["/agents"]).toBe("/control?tab=workers&view=workers");
    expect(legacyRouteRedirects["/connections"]).toBe("/control?tab=workers&view=connections");
    expect(legacyRouteRedirects["/mcp"]).toBe("/control?tab=tools&view=mcp");
    expect(legacyRouteRedirects["/skills"]).toBe("/control?tab=skills&view=skills");
    expect(legacyRouteRedirects["/skills-studio"]).toBe("/control?tab=skills&view=studio");
    expect(legacyRouteRedirects["/hatchery"]).toBe("/control?tab=models&view=hatchery");
    expect(legacyRouteRedirects["/activity"]).toBe(
      "/telemetry?tab=observability&view=activity",
    );
    expect(legacyRouteRedirects["/analytics"]).toBe(
      "/telemetry?tab=observability&view=analytics",
    );
    expect(legacyRouteRedirects["/usage"]).toBe("/telemetry?tab=observability&view=usage");
    expect(legacyRouteRedirects["/secrets"]).toBe("/telemetry?tab=security&view=secrets");
    expect(legacyRouteRedirects["/memory-privacy"]).toBe("/telemetry?tab=security&view=memory");
    expect(legacyRouteRedirects["/permissions-autonomy"]).toBe(
      "/telemetry?tab=security&view=permissions",
    );
    expect(legacyRouteRedirects["/webhooks"]).toBe("/telemetry?tab=automations&view=webhooks");
    expect(legacyRouteRedirects["/pairing"]).toBe("/telemetry?tab=automations&view=pairing");
    expect(legacyRouteRedirects["/config"]).toBe("/telemetry?tab=automations&view=config");
    // /channels was already an alias for Connections before the consolidation.
    expect(legacyRouteRedirects["/channels"]).toBe("/control?tab=workers&view=connections");
  });

  it("never redirects a path that is still a live route", () => {
    const live = new Set(workspaceRoutes.map((route) => route.to));
    for (const from of Object.keys(legacyRouteRedirects)) {
      expect(live.has(from)).toBe(false);
    }
  });

  it("builds deep-links consistently", () => {
    expect(hubLink("/control", "workers")).toBe("/control?tab=workers");
    expect(hubLink("/control", "workers", "connections")).toBe(
      "/control?tab=workers&view=connections",
    );
  });
});

describe("sectionForPath ownership", () => {
  it("treats /settings as a standalone utility", () => {
    expect(sectionForPath("/settings")).toBe("settings");
    expect(sectionForPath("/settings?section=appearance")).toBe("settings");
    expect(sectionForPath("/settings?section=si")).toBe("settings");
    expect(sectionForPath("/settings/")).toBe("settings");
  });

  it("maps the four surfaces correctly", () => {
    expect(sectionForPath("/chat")).toBe("chat");
    expect(sectionForPath("/conversation")).toBe("chat");
    expect(sectionForPath("/knowledge")).toBe("knowledge");
    expect(sectionForPath("/knowledge?tab=search")).toBe("knowledge");
    expect(sectionForPath("/control")).toBe("control");
    expect(sectionForPath("/control?tab=workers&view=connections")).toBe("control");
    expect(sectionForPath("/telemetry")).toBe("telemetry");
  });

  it("still resolves legacy paths to their new owner during the redirect tick", () => {
    expect(sectionForPath("/library")).toBe("knowledge");
    expect(sectionForPath("/agents")).toBe("control");
    expect(sectionForPath("/hatchery")).toBe("control");
    expect(sectionForPath("/config")).toBe("telemetry");
    expect(sectionForPath("/memory-privacy")).toBe("telemetry");
    expect(sectionForPath("/permissions-autonomy")).toBe("telemetry");
  });

  it("falls back to Chat for unknown paths", () => {
    expect(sectionForPath("/nope")).toBe("chat");
  });
});

describe("settings section model", () => {
  it("exposes only the five utility sections with SI first", () => {
    expect(SETTINGS_SECTIONS.map((s) => s.id)).toEqual(["si", "appearance", "chat", "rag", "app"]);
    expect(SETTINGS_SECTIONS.map((s) => s.label)).toEqual(["SI", "Appearance", "Chat", "Document Sources", "System"]);
  });

  it("normalizes legacy deep-links without losing preferences", () => {
    expect(normalizeSettingsSection("si")).toBe("si");
    expect(normalizeSettingsSection("you")).toBe("si");
    expect(normalizeSettingsSection("preferences")).toBe("si");
    expect(normalizeSettingsSection("appearance")).toBe("appearance");
    expect(normalizeSettingsSection("chat")).toBe("chat");
    expect(normalizeSettingsSection("app")).toBe("app");
    expect(normalizeSettingsSection("conversation")).toBe("chat");
    expect(normalizeSettingsSection("system")).toBe("app");
    expect(normalizeSettingsSection("plugins")).toBe("app");
    expect(normalizeSettingsSection(null)).toBe("si");
    expect(normalizeSettingsSection("unknown")).toBe("si");
  });
});
