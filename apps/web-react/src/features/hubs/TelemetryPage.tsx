import { TELEMETRY_TABS } from "@/app-navigation";

import { HubSurface } from "./HubSurface";

/** Observability, secrets and privacy, plus automations and daemon config. */
export function TelemetryPage() {
  return <HubSurface tabs={TELEMETRY_TABS} />;
}

export default TelemetryPage;
