import { KNOWLEDGE_TABS } from "@/app-navigation";

import { HubSurface } from "./HubSurface";

/** Unified library, collections, and semantic search. */
export function KnowledgeHubPage() {
  return <HubSurface tabs={KNOWLEDGE_TABS} />;
}

export default KnowledgeHubPage;
