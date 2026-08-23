import {
  FolderOpen,
  AppWindow,
  MessageSquare,
  Palette,
  Sparkles,
} from "lucide-react";

import type { SettingsSectionMeta } from "./types";

export const SETTINGS_SECTIONS: SettingsSectionMeta[] = [
  {
    id: "si",
    label: "SI",
    description: "Your Companion identity, character, and local intelligence.",
    icon: Sparkles,
  },
  {
    id: "appearance",
    label: "Appearance",
    description: "Theme, font size, and visual chrome.",
    icon: Palette,
  },
  {
    id: "chat",
    label: "Chat",
    description: "Composer defaults, transcript tools, and voice.",
    icon: MessageSquare,
  },
  {
    id: "rag",
    label: "Document Sources",
    description: "RAG indexing for search and semantic retrieval.",
    icon: FolderOpen,
  },
  {
    id: "app",
    label: "System",
    description: "Desktop integration, local runtime, access, and updates.",
    icon: AppWindow,
  },
];

/** Valid ?section= query values for the Settings hub. */
export function isSettingsSectionId(value: string | null | undefined): value is SettingsSectionMeta["id"] {
  return value === "si" || value === "appearance" || value === "chat" || value === "rag" || value === "app";
}

/** Map legacy section ids from older deep-links. */
export function normalizeSettingsSection(raw: string | null | undefined): SettingsSectionMeta["id"] {
  if (isSettingsSectionId(raw)) return raw;
  switch (raw) {
    case "you":
    case "preferences":
      return "si";
    case "conversation":
      return "chat";
    case "connections":
    case "plugins":
    case "extensions":
    case "system":
    case "help":
      return "app";
    case "appearance":
      return "appearance";
    case "rag":
    case "documents":
    case "index":
      return "rag";
    default:
      return "si";
  }
}
