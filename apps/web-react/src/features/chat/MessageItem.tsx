/**
 * WHAT: Single message bubble in the chat transcript with action bar.
 * WHERE YOU SEE IT: Chat messages area, one per user/assistant turn.
 * HOVER/TAP: Shows action bar with Copy, Branch, Retry, Model badge.
 * COPIES: This turn's text/markdown to clipboard with checkmark feedback.
 * BRANCHES: Forks session starting from this message into a new conversation.
 */

import { useState } from "react";
import { Copy, Check, GitBranch, RefreshCw, Bot } from "lucide-react";
import { Markdown } from "@/components/Markdown";
import { ToolCard } from "./ToolCard";
import { AgentActivityFeed } from "./AgentActivityFeed";

const H = {
  surface: "var(--surface)",
  surfaceHover: "#202434",
  border: "rgba(255, 255, 255, 0.08)",
  border2: "rgba(255, 255, 255, 0.12)",
  text: "#ececf1",
  muted: "#8e8ea0",
  strong: "#ffffff",
  accentGlow: "#9333ea",
};

interface MessageItemProps {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  reasoning?: string;
  toolCalls?: Array<{
    name: string;
    args?: Record<string, any>;
    output?: string;
    error?: string;
    status?: "running" | "success" | "error";
    duration?: number;
  }>;
  duration?: number;
  model?: string;
  isStreaming?: boolean;
  onCopy: (text: string) => void;
  onBranch: (messageId: string) => void;
  onRetry: (messageId: string) => void;
}

export function MessageItem({ id, role, text, reasoning, toolCalls, duration, model, isStreaming, onCopy, onBranch, onRetry }: MessageItemProps) {
  const [showActions, setShowActions] = useState(false);
  const [copied, setCopied] = useState(false);

  const isAssistant = role === "assistant";
  const isUser = role === "user";

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    onCopy(text);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleBranch = async () => {
    try {
      const response = await fetch(`/api/session/branch?session_id=${new URLSearchParams({ session_id: window.location.pathname.split('/').pop() || '' }).toString()}&keep_count=${id}`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error('Failed to branch session');
      const result = await response.json();
      // Navigate to the new forked session
      window.location.href = `/chat/${result.session_id}`;
    } catch (error) {
      console.error('Branch failed:', error);
      alert('Failed to branch session: ' + error);
    }
  };

  const handleRetry = async () => {
    try {
      // Rollback to this message and resend
      const response = await fetch('/api/chat/retry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_id: id }),
      });
      if (!response.ok) throw new Error('Failed to retry');
      // Reload the session to see the retried response
      window.location.reload();
    } catch (error) {
      console.error('Retry failed:', error);
      alert('Failed to retry: ' + error);
    }
  };

  return (
    <div
      style={{ display: "flex", width: "100%", justifyContent: isUser ? "flex-end" : "flex-start" }}
      onMouseEnter={() => isAssistant && setShowActions(true)}
      onMouseLeave={() => isAssistant && setShowActions(false)}
    >
      {!isUser && (
        <div style={{ width: "1.875rem", height: "1.875rem", borderRadius: "50%", flexShrink: 0, background: H.surface, border: `1px solid ${H.border2}`, display: "flex", alignItems: "center", justifyContent: "center", marginRight: "0.625rem", marginTop: "0.125rem" }}>
          <Bot size={14} style={{ color: H.accentGlow }} />
        </div>
      )}
      <div style={{ maxWidth: "85%", display: "flex", flexDirection: "column", alignItems: isUser ? "flex-end" : "flex-start", gap: "0.25rem" }}>
        {/* Antigravity-style unified activity feed (reasoning trace + tool execution) */}
        {isAssistant && (reasoning || (toolCalls && toolCalls.length > 0)) && (
          <AgentActivityFeed
            isLive={isStreaming}
            reasoning={reasoning}
            toolSteps={toolCalls?.map((t) => ({
              name: t.name,
              args: t.args,
              output: t.output,
              error: t.error,
              status: t.status || "success",
              duration_ms: t.duration ? t.duration * 1000 : undefined,
            }))}
            durationSec={duration}
          />
        )}
        
        {/* Message bubble */}
        <div
          style={{
            padding: "0.5625rem 0.875rem",
            fontSize: "0.875rem",
            lineHeight: 1.6,
            background: isUser ? "var(--surface-active)" : "transparent",
            color: isUser ? H.strong : H.text,
            border: isUser ? `1px solid ${H.border2}` : "none",
            borderRadius: isUser ? "0.875rem 0.875rem 0.25rem 0.875rem" : "0.875rem",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          <Markdown content={text} streaming={isStreaming} />
        </div>

        {/* Action bar - shows on hover for assistant messages */}
        {isAssistant && showActions && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.25rem",
              padding: "0.25rem 0.5rem",
              borderRadius: "0.375rem",
              background: H.surface,
              border: `1px solid ${H.border2}`,
              fontSize: "0.6875rem",
              color: H.muted,
            }}
          >
            {model && (
              <span
                style={{
                  fontSize: "0.625rem",
                  padding: "1px 0.375rem",
                  borderRadius: "0.25rem",
                  background: "rgba(124, 58, 237, 0.1)",
                  color: H.accentGlow,
                  fontWeight: 600,
                }}
              >
                {model}
              </span>
            )}
            <div style={{ width: "1px", height: "0.875rem", background: H.border2, margin: "0 0.25rem" }} />
            <button
              type="button"
              onClick={handleCopy}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.25rem",
                padding: "0.1875rem 0.375rem",
                borderRadius: "0.25rem",
                border: "none",
                background: "transparent",
                color: copied ? "#4ade80" : H.muted,
                fontSize: "0.625rem",
                fontWeight: 500,
                cursor: "pointer",
              }}
              title="Copy this message"
            >
              {copied ? <Check size={11} /> : <Copy size={11} />}
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              type="button"
              onClick={handleBranch}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.25rem",
                padding: "0.1875rem 0.375rem",
                borderRadius: "0.25rem",
                border: "none",
                background: "transparent",
                color: H.muted,
                fontSize: "0.625rem",
                fontWeight: 500,
                cursor: "pointer",
              }}
              title="Branch from this message"
            >
              <GitBranch size={11} />
              Branch
            </button>
            <button
              type="button"
              onClick={handleRetry}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.25rem",
                padding: "0.1875rem 0.375rem",
                borderRadius: "0.25rem",
                border: "none",
                background: "transparent",
                color: H.muted,
                fontSize: "0.625rem",
                fontWeight: 500,
                cursor: "pointer",
              }}
              title="Retry with different model"
            >
              <RefreshCw size={11} />
              Retry
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
