/**
 * WHAT: Live Verification Harness panel showing chat parity checklist.
 * WHERE YOU SEE IT: Side Workbench "Harness" tab.
 * FETCHES: GET /api/harness/matrix/chat-parity for verification matrix.
 * DISPLAYS: Interactive checklist with status badges (Pending/In Progress/Verified/Failed).
 * ACTIONS: Run linter verification via POST /api/harness/verify-diff.
 */

import { useState, useEffect, useCallback } from "react";
import { CheckCircle, XCircle, Clock, AlertTriangle, RefreshCw, Play } from "lucide-react";

const H = {
  surface: "var(--surface)",
  surfaceHover: "#202434",
  border: "rgba(255, 255, 255, 0.08)",
  border2: "rgba(255, 255, 255, 0.12)",
  text: "#ececf1",
  muted: "#8e8ea0",
  strong: "#ffffff",
  success: "#22c55e",
  warning: "#f59e0b",
  error: "#ef4444",
  info: "#3b82f6",
  accentBlue: "#3889FD",
};

interface FeatureRequirement {
  id: string;
  title: string;
  description: string;
  donor_reference?: string;
  target_files: string[];
  state_machine_steps: string[];
  status: "pending" | "in_progress" | "verified" | "failed";
  attempts_count: number;
  failure_details?: string;
}

interface VerificationMatrix {
  matrix_id: string;
  task_description: string;
  items: FeatureRequirement[];
  overall_status: "pending" | "in_progress" | "verified" | "failed";
  created_at: string;
  updated_at: string;
  total_items: number;
  verified_items: number;
  is_complete: boolean;
}

export function HarnessPanel() {
  const [matrix, setMatrix] = useState<VerificationMatrix | null>(null);
  const [loading, setLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [linterResult, setLinterResult] = useState<{ passed: boolean; summary: string } | null>(null);

  const fetchMatrix = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/harness/matrix/chat-parity");
      if (response.ok) {
        const data = await response.json();
        setMatrix(data);
      }
    } catch (error) {
      console.warn("Failed to fetch harness matrix:", error);
    } finally {
      setLoading(false);
    }
  }, []);

  const runVerification = useCallback(async () => {
    if (!matrix) return;
    setVerifying(true);
    setLinterResult(null);
    try {
      const response = await fetch("/api/harness/verify-diff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_description: matrix.task_description,
          diff_text: "git diff HEAD",
          verification_commands: ["npm run typecheck", "npm run build"],
        }),
      });
      if (response.ok) {
        const result = await response.json();
        setLinterResult({ passed: result.passed, summary: result.linter_summary });
      }
    } catch (error) {
      console.error("Verification failed:", error);
    } finally {
      setVerifying(false);
    }
  }, [matrix]);

  useEffect(() => {
    fetchMatrix();
  }, [fetchMatrix]);

  const statusBadge = (status: string) => {
    const config = {
      pending: { icon: Clock, color: H.muted, bg: "rgba(142,142,160,0.1)" },
      in_progress: { icon: RefreshCw, color: H.info, bg: "rgba(59,130,246,0.1)" },
      verified: { icon: CheckCircle, color: H.success, bg: "rgba(34,197,94,0.1)" },
      failed: { icon: XCircle, color: H.error, bg: "rgba(239,68,68,0.1)" },
    }[status] || { icon: Clock, color: H.muted, bg: "rgba(142,142,160,0.1)" };
    const Icon = config.icon;
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "0.25rem",
          padding: "0.1875rem 0.5rem",
          borderRadius: "0.375rem",
          fontSize: "0.6875rem",
          fontWeight: 600,
          background: config.bg,
          color: config.color,
          textTransform: "uppercase",
        }}
      >
        <Icon size={10} /> {status.replace("_", " ")}
      </span>
    );
  };

  if (loading) {
    return (
      <div style={{ padding: "1.5rem", textAlign: "center", color: H.muted }}>
        <RefreshCw size={24} className="animate-spin" style={{ margin: "0 auto 0.75rem" }} />
        <div style={{ fontSize: "0.875rem" }}>Loading verification matrix...</div>
      </div>
    );
  }

  if (!matrix) {
    return (
      <div style={{ padding: "1.5rem", textAlign: "center", color: H.muted }}>
        <AlertTriangle size={24} style={{ margin: "0 auto 0.75rem", opacity: 0.5 }} />
        <div style={{ fontSize: "0.875rem" }}>No verification matrix available</div>
      </div>
    );
  }

  return (
    <div style={{ padding: "0.75rem", display: "flex", flexDirection: "column", gap: "1rem", height: "100%", overflow: "auto" }}>
      <div>
        <h3 style={{ fontSize: "0.9375rem", fontWeight: 700, color: H.strong, margin: "0 0 0.25rem" }}>
          Chat Parity Verification
        </h3>
        <div style={{ fontSize: "0.75rem", color: H.muted }}>{matrix.matrix_id}</div>
      </div>

      <div
        style={{
          padding: "0.75rem",
          borderRadius: "8px",
          border: `1px solid ${H.border}`,
          background: H.surface,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div>
          <div style={{ fontSize: "0.8125rem", fontWeight: 600, color: H.text }}>
            {matrix.verified_items} / {matrix.total_items} Verified
          </div>
          <div style={{ fontSize: "0.6875rem", color: H.muted }}>
            {matrix.is_complete ? "All requirements met" : `${Math.round((matrix.verified_items / matrix.total_items) * 100)}% complete`}
          </div>
        </div>
        {statusBadge(matrix.overall_status)}
      </div>

      <button
        type="button"
        onClick={runVerification}
        disabled={verifying}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: "0.5rem",
          padding: "0.625rem 1rem",
          borderRadius: "8px",
          border: "none",
          background: verifying ? H.muted : H.accentBlue,
          color: "#ffffff",
          fontSize: "0.8125rem",
          fontWeight: 600,
          cursor: verifying ? "not-allowed" : "pointer",
          opacity: verifying ? 0.6 : 1,
        }}
      >
        {verifying ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
        {verifying ? "Running Linter..." : "Run Linter Verification"}
      </button>

      {linterResult && (
        <div
          style={{
            padding: "0.75rem",
            borderRadius: "8px",
            border: `1px solid ${linterResult.passed ? H.success : H.error}`,
            background: linterResult.passed ? "rgba(34,197,94,0.05)" : "rgba(239,68,68,0.05)",
          }}
        >
          <div style={{ fontSize: "0.8125rem", fontWeight: 600, color: linterResult.passed ? H.success : H.error, marginBottom: "0.25rem" }}>
            {linterResult.passed ? "✓ Linter Passed" : "✗ Linter Failed"}
          </div>
          <pre style={{ fontSize: "0.6875rem", color: H.muted, margin: 0, whiteSpace: "pre-wrap", fontFamily: "monospace" }}>
            {linterResult.summary}
          </pre>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
        <div style={{ fontSize: "0.75rem", fontWeight: 600, color: H.muted, textTransform: "uppercase" }}>Requirements</div>
        {matrix.items.map((item) => (
          <div
            key={item.id}
            style={{
              padding: "0.75rem",
              borderRadius: "8px",
              border: `1px solid ${H.border}`,
              background: H.surface,
              display: "flex",
              flexDirection: "column",
              gap: "0.5rem",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontSize: "0.8125rem", fontWeight: 600, color: H.text }}>{item.title}</div>
              {statusBadge(item.status)}
            </div>
            <div style={{ fontSize: "0.75rem", color: H.muted, lineHeight: 1.5 }}>{item.description}</div>
            {item.donor_reference && (
              <div style={{ fontSize: "0.6875rem", color: H.muted, fontFamily: "monospace" }}>
                Donor: {item.donor_reference}
              </div>
            )}
            {item.target_files.length > 0 && (
              <div style={{ fontSize: "0.6875rem", color: H.muted }}>
                Files: {item.target_files.join(", ")}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
