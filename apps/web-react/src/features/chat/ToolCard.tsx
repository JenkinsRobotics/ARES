/**
 * WHAT: Interactive card for tool execution with collapsible sections.
 * WHERE YOU SEE IT: Chat transcript, for assistant turns with tool calls.
 * HOVER/TAP: Expands/collapses to show tool args and output.
 * STATUS: Running (spinner), Success (check), Error (X icon).
 * COLLAPSES: Tool arguments and stdout/stderr output sections.
 */

import { useState } from "react";
import { Wrench, CheckCircle, XCircle, Loader2, ChevronDown, ChevronRight } from "lucide-react";

const H = {
  surface: "var(--surface)",
  surfaceHover: "#202434",
  border: "rgba(255, 255, 255, 0.08)",
  border2: "rgba(255, 255, 255, 0.12)",
  text: "#ececf1",
  muted: "#8e8ea0",
  strong: "#ffffff",
  accent: "#7c3aed",
  accentGlow: "#9333ea",
  success: "#22c55e",
  error: "#ef4444",
  running: "#f59e0b",
};

interface ToolCardProps {
  toolName: string;
  status: "running" | "success" | "error";
  args?: Record<string, any>;
  output?: string;
  error?: string;
  duration?: number;
}

export function ToolCard({ toolName, status, args, output, error, duration }: ToolCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [argsExpanded, setArgsExpanded] = useState(false);
  const [outputExpanded, setOutputExpanded] = useState(false);

  const statusIcon = {
    running: <Loader2 size={14} className="animate-spin" style={{ color: H.running }} />,
    success: <CheckCircle size={14} style={{ color: H.success }} />,
    error: <XCircle size={14} style={{ color: H.error }} />,
  }[status];

  const statusLabel = {
    running: "Running...",
    success: "Completed",
    error: "Failed",
  }[status];

  return (
    <div
      className="tool-card"
      style={{
        borderRadius: "8px",
        border: `1px solid ${H.border}`,
        borderLeft: `3px solid ${status === "running" ? H.running : status === "success" ? H.success : H.error}`,
        background: status === "running" ? "rgba(245, 158, 11, 0.05)" : "rgba(124, 58, 237, 0.03)",
        padding: "0.75rem",
        marginBottom: "0.5rem",
        transition: "background-color 0.15s, border-color 0.15s",
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          marginBottom: expanded ? "0.5rem" : "0",
        }}
      >
        <Wrench size={14} style={{ color: H.muted, flexShrink: 0 }} />
        <span
          className="tool-card-name"
          style={{
            fontWeight: 600,
            fontSize: "0.8125rem",
            color: H.text,
            flex: 1,
          }}
        >
          {toolName}
        </span>
        {statusIcon}
        <span
          style={{
            fontSize: "0.6875rem",
            color: status === "running" ? H.running : status === "success" ? H.success : H.error,
            fontWeight: 500,
          }}
        >
          {statusLabel}
        </span>
        {duration !== undefined && (
          <span
            style={{
              fontSize: "0.625rem",
              color: H.muted,
            }}
          >
            ({duration.toFixed(2)}s)
          </span>
        )}
        <button
          onClick={() => setExpanded(!expanded)}
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: "0.25rem",
            background: "transparent",
            border: "none",
            cursor: "pointer",
            color: H.muted,
          }}
          title={expanded ? "Collapse" : "Expand"}
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
      </div>

      {/* Expanded sections */}
      {expanded && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          {/* Tool arguments */}
          {args && Object.keys(args).length > 0 && (
            <div
              style={{
                borderRadius: "6px",
                border: `1px solid ${H.border}`,
                background: "rgba(0, 0, 0, 0.2)",
                overflow: "hidden",
              }}
            >
              <button
                onClick={() => setArgsExpanded(!argsExpanded)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.375rem",
                  width: "100%",
                  padding: "0.375rem 0.5rem",
                  background: "rgba(255, 255, 255, 0.03)",
                  borderBottom: argsExpanded ? `1px solid ${H.border}` : "none",
                  border: "none",
                  cursor: "pointer",
                  fontSize: "0.6875rem",
                  fontWeight: 600,
                  color: H.muted,
                  textAlign: "left",
                }}
              >
                {argsExpanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                <span className="tool-arg-key">Arguments</span>
              </button>
              {argsExpanded && (
                <pre
                  className="tool-arg-val"
                  style={{
                    padding: "0.5rem",
                    margin: 0,
                    fontSize: "0.75rem",
                    lineHeight: 1.5,
                    color: H.muted,
                    fontFamily: "monospace",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    background: "transparent",
                    overflow: "auto",
                    maxHeight: "12rem",
                  }}
                >
                  {JSON.stringify(args, null, 2)}
                </pre>
              )}
            </div>
          )}

          {/* Tool output */}
          {output && (
            <div
              className="tool-card-result"
              style={{
                borderRadius: "6px",
                border: `1px solid ${H.border}`,
                background: "rgba(0, 0, 0, 0.2)",
                overflow: "hidden",
              }}
            >
              <button
                onClick={() => setOutputExpanded(!outputExpanded)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.375rem",
                  width: "100%",
                  padding: "0.375rem 0.5rem",
                  background: "rgba(255, 255, 255, 0.03)",
                  borderBottom: outputExpanded ? `1px solid ${H.border}` : "none",
                  border: "none",
                  cursor: "pointer",
                  fontSize: "0.6875rem",
                  fontWeight: 600,
                  color: H.muted,
                  textAlign: "left",
                }}
              >
                {outputExpanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                <span>Output</span>
              </button>
              {outputExpanded && (
                <pre
                  style={{
                    padding: "0.5rem",
                    margin: 0,
                    fontSize: "0.75rem",
                    lineHeight: 1.5,
                    color: status === "error" ? H.error : H.muted,
                    fontFamily: "monospace",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    background: "transparent",
                    overflow: "auto",
                    maxHeight: "12rem",
                  }}
                >
                  {output}
                </pre>
              )}
            </div>
          )}

          {/* Error message */}
          {error && (
            <div
              style={{
                borderRadius: "6px",
                border: `1px solid ${H.error}`,
                background: "rgba(239, 68, 68, 0.05)",
                padding: "0.5rem",
                fontSize: "0.75rem",
                color: H.error,
                fontFamily: "monospace",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
