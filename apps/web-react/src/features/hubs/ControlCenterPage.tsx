import { CONTROL_TABS } from "@/app-navigation";

import { HubSurface } from "./HubSurface";

/** Workers, adapters, MCP tooling, skills, and local models in one surface. */
export function ControlCenterPage() {
  return <HubSurface tabs={CONTROL_TABS} />;
}

export default ControlCenterPage;
