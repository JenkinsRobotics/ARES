import { useEffect, useRef, useState } from "react";
import { aresApi } from "@/shared/ares-api";

/**
 * WHAT: Live delegation log viewer in the Workspace panel.
 * WHERE YOU SEE IT: Right side panel, "Agents" tab (next to Files/Artifacts).
 * WHAT IT DOES: Lists active/completed delegate agents and streams their live logs.
 * HOW IT WORKS: Polls ~/.hermes/cache/delegation/live/*.log every 2s, auto-scrolls to bottom.
 * WHEN IT HIDES: When the Workbench panel is collapsed.
 */

interface DelegationTask {
  delegationId: string;
  taskIndex: number;
  logPath: string;
  goal: string;
  status: "running" | "completed";
}

export function AgentsTab() {
  const [tasks, setTasks] = useState<DelegationTask[]>([]);
  const [selectedTask, setSelectedTask] = useState<DelegationTask | null>(null);
  const [logContent, setLogContent] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Poll for delegation tasks every 2 seconds
  useEffect(() => {
    const pollTasks = async () => {
      try {
        const liveLogs = await aresApi.getDelegationLogs();
        const taskList: DelegationTask[] = [];
        
        for (const delegation of liveLogs.delegations || []) {
          for (let i = 0; i < delegation.taskCount; i++) {
            taskList.push({
              delegationId: delegation.id,
              taskIndex: i,
              logPath: delegation.logPaths?.[i] || "",
              goal: delegation.goals?.[i] || "",
              status: (delegation.status as "running" | "completed") || "running",
            });
          }
        }
        
        setTasks(taskList);
        
        // If a task is selected and still exists, keep it selected
        if (selectedTask) {
          const stillExists = taskList.find(
            t => t.delegationId === selectedTask.delegationId && t.taskIndex === selectedTask.taskIndex
          );
          if (!stillExists) {
            setSelectedTask(null);
            setLogContent("");
          }
        }
      } catch (err) {
        console.error("Failed to poll delegation logs:", err);
      }
    };

    pollTasks();
    const interval = setInterval(pollTasks, 2000);
    return () => clearInterval(interval);
  }, [selectedTask]);

  // Load log content when a task is selected
  useEffect(() => {
    if (!selectedTask) return;

    const loadLog = async () => {
      try {
        const content = await aresApi.readDelegationLog(selectedTask.logPath);
        setLogContent(content);
      } catch (err) {
        setLogContent(`Error loading log: ${err instanceof Error ? err.message : "Unknown error"}`);
      }
    };

    loadLog();
    const interval = setInterval(loadLog, 1500);
    return () => clearInterval(interval);
  }, [selectedTask]);

  // Auto-scroll to bottom when log updates
  useEffect(() => {
    if (autoScroll && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logContent, autoScroll]);

  return (
    <div style={{ display: "flex", height: "100%", background: "var(--workbench-bg)", color: "var(--text)" }}>
      {/* Task list sidebar */}
      <div style={{ width: "280px", borderRight: "1px solid var(--border)", overflowY: "auto" }}>
        <div style={{ padding: "0.75rem", fontWeight: 600, borderBottom: "1px solid var(--border)" }}>
          Active Agents
        </div>
        {tasks.length === 0 ? (
          <div style={{ padding: "1rem", color: "var(--muted)", fontSize: "0.875rem" }}>
            No active agents. Start a delegation to see live logs here.
          </div>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {tasks.map((task) => (
              <li key={`${task.delegationId}-task-${task.taskIndex}`}>
                <button
                  type="button"
                  onClick={() => setSelectedTask(task)}
                  style={{
                    width: "100%",
                    padding: "0.625rem 0.75rem",
                    background: selectedTask?.logPath === task.logPath ? "var(--surface-hover)" : "transparent",
                    border: "none",
                    borderBottom: "1px solid var(--border)",
                    color: "var(--text)",
                    textAlign: "left",
                    cursor: "pointer",
                    fontSize: "0.75rem",
                  }}
                >
                  <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>
                    {task.status === "running" ? "🟢" : "⚪"} Task {task.taskIndex}
                  </div>
                  <div style={{ color: "var(--muted)", fontSize: "0.6875rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {task.goal}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Log viewer */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Header */}
        <div style={{ padding: "0.5rem 0.75rem", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontWeight: 600, fontSize: "0.875rem" }}>
            {selectedTask ? `Task ${selectedTask.taskIndex}` : "Select an agent"}
          </div>
          <label style={{ fontSize: "0.75rem", color: "var(--muted)", display: "flex", alignItems: "center", gap: "0.375rem" }}>
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              style={{ accentColor: "var(--accent)" }}
            />
            Auto-scroll
          </label>
        </div>

        {/* Log content */}
        <pre
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "0.75rem",
            margin: 0,
            fontSize: "0.75rem",
            fontFamily: "ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            background: "var(--surface)",
            color: "var(--muted)",
          }}
        >
          {selectedTask ? logContent : "Select a task from the list to view its live log."}
          <div ref={logEndRef} />
        </pre>
      </div>
    </div>
  );
}
