import { WorkspaceShell } from "@/components/shell/WorkspaceShell";

/**
 * Compatibility export for the route boundary. The actual shell is split into
 * focused command-center modules so navigation, panes, and workbench behavior
 * can evolve independently.
 */
export function AppShell() {
  return <WorkspaceShell />;
}
