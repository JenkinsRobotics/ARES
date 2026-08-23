import { Suspense, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import type { HubTab } from "@/app-navigation";
import { cn } from "@/lib/utils";

function HubFallback() {
  return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
}

/**
 * Shared chrome for the consolidated hub surfaces.
 *
 * Each hub owns a primary tab bar; a tab that hosts more than one legacy page
 * gets a secondary segmented control beneath it. Selection lives in the URL
 * (`?tab=…&view=…`) so every pane stays deep-linkable and shareable exactly as
 * the standalone routes were.
 *
 * Child pages supply their own `SurfaceShell` header, so this renders only the
 * navigation and the active pane — no second header, no double padding.
 */
export function HubSurface({ tabs }: { tabs: HubTab[] }) {
  const [searchParams, setSearchParams] = useSearchParams();

  const activeTab = useMemo(() => {
    const requested = searchParams.get("tab");
    return tabs.find((tab) => tab.id === requested) ?? tabs[0];
  }, [searchParams, tabs]);

  const activeView = useMemo(() => {
    if (!activeTab) return undefined;
    const requested = searchParams.get("view");
    return activeTab.views.find((view) => view.id === requested) ?? activeTab.views[0];
  }, [activeTab, searchParams]);

  const select = useCallback(
    (tabId: string, viewId?: string) => {
      const next = new URLSearchParams(searchParams);
      next.set("tab", tabId);
      if (viewId) next.set("view", viewId);
      else next.delete("view");
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  if (!activeTab || !activeView) return null;

  const ActiveComponent = activeView.component;
  const hasViews = activeTab.views.length > 1;

  return (
    <div className="flex min-h-0 w-full flex-col">
      <div className="border-b border-border/70 bg-background/60">
        <div className="mx-auto w-full max-w-5xl px-6 pt-4">
          <nav className="flex flex-wrap items-center gap-1" aria-label="Hub sections">
            {tabs.map(({ id, label, icon: Icon }) => {
              const isActive = id === activeTab.id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => select(id)}
                  aria-current={isActive ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
                    isActive
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                  )}
                >
                  <Icon className="size-3.5 shrink-0" />
                  <span className="truncate">{label}</span>
                </button>
              );
            })}
          </nav>

          <p className="px-1 pt-2 text-xs text-muted-foreground">{activeTab.blurb}</p>

          {hasViews ? (
            <div
              className="mt-2 flex flex-wrap items-center gap-1 pb-1"
              role="tablist"
              aria-label={`${activeTab.label} views`}
            >
              {activeTab.views.map(({ id, label }) => {
                const isActive = id === activeView.id;
                return (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    onClick={() => select(activeTab.id, id)}
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
                      isActive
                        ? "border-primary/50 bg-primary/10 text-foreground"
                        : "border-border/70 text-muted-foreground hover:border-border hover:text-foreground",
                    )}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          ) : null}

          <div className="h-3" />
        </div>
      </div>

      <div className="min-h-0 flex-1">
        <Suspense fallback={<HubFallback />}>
          <ActiveComponent key={`${activeTab.id}:${activeView.id}`} />
        </Suspense>
      </div>
    </div>
  );
}
