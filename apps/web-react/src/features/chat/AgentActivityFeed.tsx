/**
 * WHAT: Live agent action feed and collapsible "Worked for Xs" execution block.
 * WHERE YOU SEE IT: Chat transcript, for assistant turns with tool actions or reasoning.
 * BEHAVIOR:
 *   - LIVE: Counts seconds actively ("Working for 12s..."), shows running steps in real time.
 *   - DONE: Collapses into a sleek "Worked for 43s ▾" accordion, expandable on demand.
 *   - TRANSPARENCY: Preserves 100% inspectability for all tool calls, arguments, and outputs (Doctrine II).
 */

import { useState, useEffect, useMemo } from "react";
import {
  Terminal,
  FileText,
  Search,
  Wrench,
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import type { ToolStepData } from "@/shared/chat-stream";

const H = {
  surface: "var(--surface, #181a20)",
  surfaceHover: "var(--surface-hover, #202434)",
  border: "var(--border, rgba(255, 255, 255, 0.08))",
  border2: "var(--border2, rgba(255, 255, 255, 0.12))",
  text: "var(--text, #ececf1)",
  muted: "var(--muted, #8e8ea0)",
  strong: "var(--strong, #ffffff)",
  accent: "#7c3aed",
  accentGlow: "#9333ea",
  accentBlue: "#3889fd",
  success: "#22c55e",
  error: "#ef4444",
  running: "#f59e0b",
};

export interface AgentActivityFeedProps {
  isLive?: boolean;
  startTime?: number | null;
  durationSec?: number;
  reasoning?: string;
  toolSteps?: ToolStepData[];
  toolNames?: string[];
}

function formatToolActionLabel(name: string, args?: Record<string, any>): { prefix: string; detail: string; kind: "cmd" | "file" | "search" | "tool" } {
  const low = name.toLowerCase();
  if (low.includes("command") || low.includes("bash") || low.includes("terminal") || low.includes("exec") || low.includes("run")) {
    const cmd = args?.CommandLine || args?.command || args?.cmd || "";
    return {
      prefix: "Ran",
      detail: cmd ? (cmd.length > 65 ? cmd.slice(0, 62) + "…" : cmd) : name,
      kind: "cmd",
    };
  }
  if (low.includes("search") || low.includes("grep")) {
    const query = args?.query || args?.Query || args?.q || args?.pattern || "";
    return {
      prefix: "Searched",
      detail: query ? (query.length > 55 ? query.slice(0, 52) + "…" : query) : name,
      kind: "search",
    };
  }
  if (low.includes("file") || low.includes("read") || low.includes("view") || low.includes("write") || low.includes("replace")) {
    const path = args?.AbsolutePath || args?.TargetFile || args?.path || args?.file || "";
    const basename = path ? path.split("/").filter(Boolean).pop() || path : "";
    const prefix = low.includes("write") ? "Wrote" : low.includes("replace") || low.includes("edit") ? "Edited" : "Explored";
    return {
      prefix,
      detail: basename || name,
      kind: "file",
    };
  }
  return {
    prefix: "Executed",
    detail: name,
    kind: "tool",
  };
}

export function AgentActivityFeed({
  isLive = false,
  startTime = null,
  durationSec,
  reasoning,
  toolSteps = [],
  toolNames = [],
}: AgentActivityFeedProps) {
  const [elapsed, setElapsed] = useState<number>(() => {
    if (durationSec !== undefined) return durationSec;
    if (startTime) return Math.max(1, Math.floor((Date.now() - startTime) / 1000));
    return 1;
  });

  // Default expanded while live so user watches the work, collapsed when finished
  const [expanded, setExpanded] = useState<boolean>(isLive);
  const [expandedStepIndex, setExpandedStepIndex] = useState<number | null>(null);
  const [reasoningExpanded, setReasoningExpanded] = useState<boolean>(false);

  // Live timer tick
  useEffect(() => {
    if (!isLive) return;
    const start = startTime || Date.now();
    const timer = setInterval(() => {
      setElapsed(Math.max(1, Math.floor((Date.now() - start) / 1000)));
    }, 1000);
    return () => clearInterval(timer);
  }, [isLive, startTime]);

  // Combine rich tool steps and simple tool name tags
  const aggregatedSteps: ToolStepData[] = useMemo(() => {
    if (toolSteps.length > 0) return toolSteps;
    return toolNames.map((name) => ({
      name,
      status: isLive ? "running" : "success",
    }));
  }, [toolSteps, toolNames, isLive]);

  const hasReasoning = Boolean(reasoning && reasoning.trim());
  const hasTools = aggregatedSteps.length > 0;
  const hasActivity = hasReasoning || hasTools || isLive;

  if (!hasActivity) return null;

  const headerLabel = isLive
    ? `Working for ${elapsed}s…`
    : `Worked for ${durationSec !== undefined ? durationSec : elapsed}s`;

  return (
    <div
      className="agent-activity-feed"
      style={{
        width: "100%",
        borderRadius: "0.5rem",
        border: `1px solid ${isLive ? "rgba(124, 58, 237, 0.25)" : H.border}`,
        background: isLive ? "rgba(124, 58, 237, 0.04)" : "rgba(255, 255, 255, 0.02)",
        marginBottom: "0.625rem",
        overflow: "hidden",
        fontSize: "0.8125rem",
        transition: "border-color 0.2s ease, background 0.2s ease",
      }}
    >
      {/* Collapsible summary header */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded((prev) => !prev)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setExpanded((prev) => !prev);
          }
        }}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0.4375rem 0.75rem",
          background: isLive ? "rgba(124, 58, 237, 0.08)" : "rgba(255, 255, 255, 0.03)",
          borderBottom: expanded ? `1px solid ${H.border}` : "none",
          cursor: "pointer",
          userSelect: "none",
          color: isLive ? H.text : H.muted,
          fontWeight: 500,
        }}
      >
        {isLive ? (
          <Loader2 size={13} className="animate-spin" style={{ color: H.accentBlue, flexShrink: 0 }} />
        ) : (
          <Sparkles size={13} style={{ color: H.accentGlow, opacity: 0.85, flexShrink: 0 }} />
        )}
        <span style={{ fontSize: "0.75rem", color: isLive ? H.strong : H.text, fontWeight: 600 }}>
          {headerLabel}
        </span>

        {aggregatedSteps.length > 0 && (
          <span style={{ fontSize: "0.6875rem", color: H.muted, opacity: 0.8 }}>
            • {aggregatedSteps.length} {aggregatedSteps.length === 1 ? "action" : "actions"}
          </span>
        )}

        <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "0.25rem", fontSize: "0.6875rem", color: H.muted }}>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </div>

      {/* Expanded body containing live action feed and reasoning trace */}
      {expanded && (
        <div style={{ padding: "0.625rem 0.75rem", display: "flex", flexDirection: "column", gap: "0.4375rem" }}>
          {/* Action Step Rows */}
          {aggregatedSteps.map((step, idx) => {
            const { prefix, detail, kind } = formatToolActionLabel(step.name, step.args);
            const isStepExpanded = expandedStepIndex === idx;
            const isRunning = step.status === "running";
            const isError = step.status === "error";

            const Icon = kind === "cmd"
              ? Terminal
              : kind === "search"
              ? Search
              : kind === "file"
              ? FileText
              : Wrench;

            return (
              <div
                key={step.id || `${step.name}-${idx}`}
                style={{
                  borderRadius: "0.375rem",
                  background: isStepExpanded ? "rgba(0, 0, 0, 0.25)" : "transparent",
                  border: isStepExpanded ? `1px solid ${H.border2}` : "1px solid transparent",
                  overflow: "hidden",
                  transition: "background 0.15s ease",
                }}
              >
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => setExpandedStepIndex(isStepExpanded ? null : idx)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    padding: "0.25rem 0.375rem",
                    cursor: "pointer",
                    fontSize: "0.75rem",
                  }}
                >
                  <Icon size={12} style={{ color: H.muted, flexShrink: 0 }} />
                  <span style={{ color: H.muted, fontWeight: 500 }}>{prefix}</span>
                  <span
                    style={{
                      color: H.text,
                      fontFamily: kind === "cmd" ? "monospace" : "inherit",
                      fontSize: kind === "cmd" ? "0.6875rem" : "0.75rem",
                      background: kind === "cmd" ? "rgba(255, 255, 255, 0.05)" : "transparent",
                      padding: kind === "cmd" ? "0.1rem 0.3rem" : "0",
                      borderRadius: "0.25rem",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      maxWidth: "28rem",
                    }}
                  >
                    {detail}
                  </span>

                  <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "0.375rem", flexShrink: 0 }}>
                    {isRunning ? (
                      <Loader2 size={11} className="animate-spin" style={{ color: H.running }} />
                    ) : isError ? (
                      <XCircle size={11} style={{ color: H.error }} />
                    ) : (
                      <CheckCircle2 size={11} style={{ color: H.success, opacity: 0.8 }} />
                    )}

                    {step.duration_ms !== undefined && (
                      <span style={{ fontSize: "0.625rem", color: H.muted, fontFamily: "monospace" }}>
                        {(step.duration_ms / 1000).toFixed(1)}s
                      </span>
                    )}

                    {(step.args || step.output || step.error) && (
                      <span style={{ color: H.muted, opacity: 0.6 }}>
                        {isStepExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                      </span>
                    )}
                  </div>
                </div>

                {/* Inspectable tool details (Doctrine II: The Glass Box) */}
                {isStepExpanded && (
                  <div
                    style={{
                      padding: "0.5rem 0.625rem",
                      background: "rgba(0, 0, 0, 0.35)",
                      borderTop: `1px solid ${H.border}`,
                      fontSize: "0.6875rem",
                      display: "flex",
                      flexDirection: "column",
                      gap: "0.375rem",
                    }}
                  >
                    {step.args && (
                      <div>
                        <div style={{ fontWeight: 600, color: H.muted, marginBottom: "0.125rem" }}>Parameters:</div>
                        <pre
                          style={{
                            margin: 0,
                            padding: "0.375rem",
                            borderRadius: "0.25rem",
                            background: "rgba(0, 0, 0, 0.4)",
                            color: "#a5b4fc",
                            overflowX: "auto",
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-word",
                          }}
                        >
                          {JSON.stringify(step.args, null, 2)}
                        </pre>
                      </div>
                    )}

                    {step.output && (
                      <div>
                        <div style={{ fontWeight: 600, color: H.muted, marginBottom: "0.125rem" }}>Output:</div>
                        <pre
                          style={{
                            margin: 0,
                            padding: "0.375rem",
                            borderRadius: "0.25rem",
                            background: "rgba(0, 0, 0, 0.4)",
                            color: H.text,
                            overflowX: "auto",
                            maxHeight: "10rem",
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-word",
                          }}
                        >
                          {step.output}
                        </pre>
                      </div>
                    )}

                    {step.error && (
                      <div>
                        <div style={{ fontWeight: 600, color: H.error, marginBottom: "0.125rem" }}>Error:</div>
                        <pre
                          style={{
                            margin: 0,
                            padding: "0.375rem",
                            borderRadius: "0.25rem",
                            background: "rgba(239, 68, 68, 0.1)",
                            color: "#fca5a5",
                            overflowX: "auto",
                            whiteSpace: "pre-wrap",
                          }}
                        >
                          {step.error}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {/* Collapsible thinking / reasoning stream */}
          {hasReasoning && (
            <div
              style={{
                marginTop: "0.25rem",
                borderRadius: "0.375rem",
                border: `1px solid ${H.border}`,
                background: "rgba(124, 58, 237, 0.03)",
                overflow: "hidden",
              }}
            >
              <div
                role="button"
                tabIndex={0}
                onClick={() => setReasoningExpanded((prev) => !prev)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.375rem",
                  padding: "0.25rem 0.5rem",
                  background: "rgba(124, 58, 237, 0.06)",
                  cursor: "pointer",
                  fontSize: "0.6875rem",
                  fontWeight: 600,
                  color: H.muted,
                  userSelect: "none",
                }}
              >
                <span>Thinking Process</span>
                <span style={{ opacity: 0.6, fontWeight: 400 }}>
                  ({(reasoning || "").split(/\s+/).filter(Boolean).length} words)
                </span>
                <span style={{ marginLeft: "auto" }}>
                  {reasoningExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                </span>
              </div>
              {reasoningExpanded && (
                <div
                  style={{
                    padding: "0.5rem 0.625rem",
                    fontSize: "0.75rem",
                    lineHeight: 1.5,
                    color: H.muted,
                    fontStyle: "italic",
                    whiteSpace: "pre-wrap",
                    maxHeight: "15rem",
                    overflowY: "auto",
                  }}
                >
                  {reasoning}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
