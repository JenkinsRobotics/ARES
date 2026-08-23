import {
  ArrowDown,
  Bot,
  Check,
  Copy,
  LoaderCircle,
  Square,
  Wrench,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  X,
  Paperclip,
  Bookmark,
  Mic,
  MicOff,
  Boxes,
  Folder,
  FileText,
  GitBranch,
  Settings,
  Server,
  User,
  Package,
  Brain,
  Zap,
  WrenchIcon,
  SlidersHorizontal,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useDynamicOverflow, type DensityPreference } from "./composer/useDynamicOverflow";

import { Link, useSearchParams, useNavigate } from "react-router-dom";

import { APP_ICON_URL } from "@/assets";
import { isBlockingState } from "@/components/ConnectionStatusBadge";
import { Markdown } from "@/components/Markdown";
import { AgentActivityFeed } from "./AgentActivityFeed";
import { useAres } from "@/shared/ares-context";
import { aresApi } from "@/shared/ares-api";
import { useLocalProfile } from "@/shared/local-profile";
import { useWorkbenchPanel } from "@/shared/workbench-panel";
import { apiFetch, readableError, PROVIDER_UNAVAILABLE_CODES } from "@/shared/api-client";
import { backendLabel } from "@/shared/backend-catalog";
import { MessageItem } from "@/features/chat/MessageItem";
import { Chip } from "./composer/Chip";
import { ComposerPopover } from "@/components/ui/ComposerPopover";

// Hermes-matching dark blue palette
const H = {
  bg: "var(--chat-bg)",
  surface: "var(--chat-surface)",
  surfaceHover: "#1f2236",
  surfaceActive: "#252840",
  border: "#1e2130",
  border2: "#2a2d42",
  text: "#e2e4f0",
  strong: "#f0f2ff",
  muted: "#6b7194",
  accentGlow: "#08EBF1",
  accentBlue: "#3889FD",
  accent: "#5b7cf6",
  inputBg: "#161822",
  inputBorder: "#252840",
  chipBg: "#1e2130",
  chipBorder: "#2a2d42",
  chipText: "#9094b8",
  sendBtn: "#ef4444",
  sendBtnText: "#ffffff",
};

// ARES Spartan Helmet - uses the actual icon from assets
const SpartanHelmetSVG = () => (
  <img src={APP_ICON_URL} alt="ARES Spartan Helmet" style={{ width: "72px", height: "72px", objectFit: "contain" }} />
);

function IconBtn({ children, title, onClick }: { children: React.ReactNode; title: string; onClick?: () => void }) {
  return (
    <button type="button" title={title} onClick={onClick}
      style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "1.75rem", height: "1.75rem", borderRadius: "0.375rem", border: "none", background: "transparent", color: H.muted, cursor: "pointer", transition: "color 0.15s, background 0.15s" }}
      onMouseEnter={(e) => { e.currentTarget.style.color = H.text; e.currentTarget.style.background = "rgba(255,255,255,0.06)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.color = H.muted; e.currentTarget.style.background = "transparent"; }}>
      {children}
    </button>
  );
}

function formatShortModelLabel(label: string): string {
  if (!label || label === "auto") return "Auto";
  const primary = label.split("·")[0].trim();
  return primary
    .replace(/-\d{8}$/, "")
    .replace(/^gpt-4o/, "GPT-4o")
    .replace(/^claude-3-5-sonnet/, "Claude 3.5")
    .replace(/^grok-/, "Grok ");
}

function SwitchboardLED({ active = true, color = "emerald", pulse = false, title }: { active?: boolean; color?: "emerald" | "purple" | "cyan" | "amber" | "red"; pulse?: boolean; title?: string }) {
  const colorMap = {
    emerald: "#10b981",
    purple: "#a855f7",
    cyan: "#08ebf1",
    amber: "#f59e0b",
    red: "#ef4444",
  };
  const activeColor = colorMap[color] || colorMap.emerald;
  return (
    <span
      title={title}
      style={{
        display: "inline-block",
        width: "5px",
        height: "5px",
        borderRadius: "50%",
        background: active ? activeColor : "rgba(255,255,255,0.2)",
        boxShadow: active ? `0 0 6px ${activeColor}` : "none",
        flexShrink: 0,
        animation: pulse && active ? "aresLedPulse 1.5s ease-in-out infinite" : "none",
      }}
    />
  );
}

function ComposerChip({ icon, label, onClick, title, maxWidth, ledColor, ledPulse }: { icon: React.ReactNode; label: string; onClick?: () => void; title?: string; maxWidth?: string; ledColor?: "emerald" | "purple" | "cyan" | "amber" | "red"; ledPulse?: boolean }) {
  const [hover, setHover] = useState(false);
  return (
    <button type="button" title={title || label} onClick={onClick} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem", height: "1.5rem", padding: "0 0.375rem", borderRadius: "0.375rem", border: `1px solid ${hover ? H.border2 : H.chipBorder}`, background: hover ? H.surfaceHover : H.chipBg, color: hover ? H.text : H.chipText, fontSize: "0.6875rem", fontWeight: 500, cursor: "pointer", transition: "all 0.15s", whiteSpace: "nowrap", flexShrink: 1, minWidth: 0, maxWidth: maxWidth || "7.5rem" }}>
      {ledColor && <SwitchboardLED active={true} color={ledColor} pulse={ledPulse} />}
      <span style={{ opacity: 0.7, flexShrink: 0 }}>{icon}</span>
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flexShrink: 1, minWidth: 0 }}>{label}</span>
      <ChevronDown size={9} style={{ opacity: 0.5, flexShrink: 0 }} />
    </button>
  );
}



interface DiscoveredBackend {
  adapter_id: string;
  display_name: string;
  detected: boolean;
}

interface DiscoveryResponse {
  adapters: DiscoveredBackend[];
}

const SAVED_PROMPT_TEMPLATES = [
  { label: "Code Review", prompt: "Please review this code for performance, security vulnerabilities, and adherence to clean architecture principles:" },
  { label: "Debug Error", prompt: "Help me diagnose and debug the root cause of this error. Trace the failure path step by step:" },
  { label: "Refactor Code", prompt: "Refactor this code to make it more modular, readable, and maintainable while maintaining exact backward compatibility:" },
  { label: "System Architecture", prompt: "Outline a high-level technical architecture and implementation plan for the following feature requirement:" },
];

/** Available Jaeger AI character/personality presets — mirrors backend config.yaml agent.personalities */
const PERSONALITY_OPTIONS: Array<{ id: string; label: string; detail: string }> = [
  { id: "grounded", label: "Grounded", detail: "Practical, direct, no fluff — matches your onboarding character" },
  { id: "helpful", label: "Helpful", detail: "Friendly and thorough, assists accurately and completely" },
  { id: "concise", label: "Concise", detail: "Brief and to the point — minimal words, maximum signal" },
  { id: "technical", label: "Technical", detail: "Detailed, precise technical information and analysis" },
  { id: "creative", label: "Creative", detail: "Think outside the box, innovative solutions" },
  { id: "warm", label: "Warm", detail: "Caring, empathetic, supportive conversational style" },
  { id: "direct", label: "Direct", detail: "No sugar-coating, straight answers, efficient" },
  { id: "curious", label: "Curious", detail: "Asks clarifying questions, explores implications deeply" },
  { id: "teacher", label: "Teacher", detail: "Patient explanations with examples and analogies" },
  { id: "noir", label: "Noir", detail: "Hard-boiled detective style, atmospheric and sharp" },
  { id: "catgirl", label: "Neko-chan", detail: "Playful catgirl companion, nya~!" },
  { id: "pirate", label: "Pirate", detail: "Arrr! Tech-savvy buccaneer of the digital seas" },
  { id: "shakespeare", label: "Shakespeare", detail: "Flowery prose and dramatic flair" },
  { id: "uwu", label: "UwU", detail: "Maximum cuteness, hewwo fwiend!" },
  { id: "philosopher", label: "Philosopher", detail: "Contemplates the deeper meaning behind every query" },
  { id: "hype", label: "Hype", detail: "YOOO LET'S GOOO! Maximum energy, minimum chill" },
  { id: "kawaii", label: "Kawaii", detail: "Sparkles and enthusiasm for everything desu~!" },
  { id: "surfer", label: "Surfer", detail: "Duuude, chillest companion on the web, bro!" },
];

const REASONING_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "none", label: "Off" },
  { value: "minimal", label: "Minimal" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "Extra High" },
  { value: "max", label: "Max" },
  { value: "ultra", label: "Ultra" },
];

export function ConversationPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const workbenchPanel = useWorkbenchPanel();
  const { profile } = useLocalProfile();
  const {
    snapshot,
    currentSession,
    selectedSessionId,
    createSession,
    sendMessage,
    streamText,
    streamReasoning,
    streamTools,
    streamToolSteps,
    streamStartTime,
    streamState,
    chatNotice,
    chatNoticeProvider,
    cancelResponse,
    refresh,
  } = useAres();

  const sessionLoading = Boolean(selectedSessionId && !currentSession && !chatNotice);
  const [draft, setDraft] = useState("");
  const [copied, setCopied] = useState(false);
  const [showScrollBottom, setShowScrollBottom] = useState(false);
  const [discoveredBackends, setDiscoveredBackends] = useState<DiscoveredBackend[]>([]);
  const [discoveryError, setDiscoveryError] = useState("");
  const [selectedBackend, setSelectedBackend] = useState<string>(() => currentSession?.backendId || "");
  const [selectedPersonality, setSelectedPersonality] = useState<string>(() => profile.character || "grounded");
  const [showApproval, setShowApproval] = useState(false);
  const [approvalCollapsed, setApprovalCollapsed] = useState(false);

  // Attachments, saved prompts, dictation, workspace, backend, model
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  
  // Dynamic overflow detection (donor: ui.js _fitComposerFooter)
  const { stage: overflowStage, containerRef: overflowContainerRef, setDensity, density } = useDynamicOverflow("auto");
  const [showSavedPrompts, setShowSavedPrompts] = useState(false);
  const [showBackendMenu, setShowBackendMenu] = useState(false);
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [providerHealth, setProviderHealth] = useState<Record<string, { status: string; details: string; reset_eta?: string }>>({});
  const [customModelId, setCustomModelId] = useState("");

  // Fetch live provider health & reset ETAs whenever model menu opens
  useEffect(() => {
    if (showModelMenu) {
      fetch("/api/providers/health")
        .then((res) => res.json())
        .then((data) => {
          if (data && Array.isArray(data.providers)) {
            const map: Record<string, { status: string; details: string; reset_eta?: string }> = {};
            for (const p of data.providers) {
              map[p.id] = p;
            }
            setProviderHealth(map);
          }
        })
        .catch(() => {});
    }
  }, [showModelMenu]);
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const [closedGroups, setClosedGroups] = useState<Set<string>>(new Set());
  const [showWorkspaceMenu, setShowWorkspaceMenu] = useState(false);
  const [showSiModeMenu, setShowSiModeMenu] = useState(false);
  const [showReasoningMenu, setShowReasoningMenu] = useState(false);
  const [showToolsetMenu, setShowToolsetMenu] = useState(false);
  const [showMobileOverflow, setShowMobileOverflow] = useState(false);
  const [selectedReasoning, setSelectedReasoning] = useState<string>("medium");
  const [supportedEfforts, setSupportedEfforts] = useState<string[]>([]);
  const [supportsThinkingToggle, setSupportsThinkingToggle] = useState<boolean>(true);
  const [yoloMode, setYoloMode] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [selectedModelProvider, setSelectedModelProvider] = useState<string>("");
  const [modelSearchQuery, setModelSearchQuery] = useState<string>("");
  const [workspaceOverride, setWorkspaceOverride] = useState<string>("");

  useEffect(() => {
    const handoff = searchParams.get("prompt")?.trim();
    if (!handoff) return;
    setDraft((current) => current || handoff);
    const next = new URLSearchParams(searchParams);
    next.delete("prompt");
    next.delete("source");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);
  const [backendCatalog, setBackendCatalog] = useState<
    Array<{
      id: string;
      available?: boolean;
      inventory?: {
        models?: Array<{
          id: string;
          label?: string;
          location?: string;
          in_use?: boolean;
          provider?: string | null;
          notes?: string | null;
        }>;
        providers?: Array<{ id: string; label?: string; status?: string; notes?: string }>;
        active_execution?: { model?: string | null; provider?: string | null };
      };
    }>
  >([]);

  const [wsSearchQuery, setWsSearchQuery] = useState("");
  const [backendSearchQuery, setBackendSearchQuery] = useState("");

  // Composer / transcript prefs from App Settings (agent-agnostic server keys).
  const [sendKey, setSendKey] = useState<"enter" | "ctrl+enter" | "shift+enter">("enter");
  const [hideSuggestions, setHideSuggestions] = useState(false);
  const [autoFollow, setAutoFollow] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void aresApi
      .settingsGet()
      .then((raw) => {
        if (cancelled) return;
        const key = String(raw.send_key || "enter");
        if (key === "ctrl+enter" || key === "shift+enter" || key === "enter") setSendKey(key);
        setHideSuggestions(Boolean(raw.hide_empty_state_suggestions));
        setAutoFollow(raw.auto_scroll_follow !== false);
      })
      .catch(() => {
        /* keep defaults */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const copiedTimer = useRef<number | undefined>(undefined);
  const backendSessionId = useRef<string>("");
  const transcriptRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<any>(null);
  const backendTriggerRef = useRef<HTMLDivElement>(null);
  const workspaceTriggerRef = useRef<HTMLDivElement>(null);
  const modelTriggerRef = useRef<HTMLDivElement>(null);
  const reasoningTriggerRef = useRef<HTMLDivElement>(null);
  const toolsetTriggerRef = useRef<HTMLDivElement>(null);
  const mobileOverflowTriggerRef = useRef<HTMLDivElement>(null);

  // Close menus when clicking outside
  useEffect(() => {
    const handleDocumentClick = (e: MouseEvent) => {
      // Don't close if click is inside any menu wrapper or composer popover portal
      const target = e.target as HTMLElement;
      if (target.closest?.("[data-menu-wrapper]") || target.closest?.("[data-composer-popover]")) return;
      setShowWorkspaceMenu(false);
      setShowBackendMenu(false);
      setShowModelMenu(false);
      setShowSiModeMenu(false);
      setShowReasoningMenu(false);
      setShowToolsetMenu(false);
      setShowMobileOverflow(false);
    };
    document.addEventListener("click", handleDocumentClick);
    return () => document.removeEventListener("click", handleDocumentClick);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void apiFetch<DiscoveryResponse>("/api/discover/frameworks", { signal: controller.signal })
      .then((data) => {
        if (controller.signal.aborted) return;
        setDiscoveredBackends(data.adapters || []);
        setDiscoveryError("");
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setDiscoveryError(readableError(error, "Connections could not be discovered."));
      });
    void apiFetch<{ backends?: typeof backendCatalog }>("/api/backends", { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setBackendCatalog(data.backends || []);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => () => {
    if (copiedTimer.current !== undefined) window.clearTimeout(copiedTimer.current);
  }, []);

  const isBusy = streamState !== "idle";
  const hasConversation = Boolean(currentSession?.messages.length || streamText || isBusy);
  const isReadOnlyCli = Boolean(currentSession?.readOnly || currentSession?.source === "cli");

  // Whether the chosen provider can actually take a turn. The server refuses
  // one it cannot serve, but letting someone type a message and press send only
  // to be told no is a poor way to learn the provider is down — so the composer
  // says it up front and stays out of the way.
  // Prefer local chip, then server election, then connections.
  // Local starts empty while phase-1 already has snapshot.selectedBackend —
  // using only local state produced "No models" with a working elected backend.
  const effectiveBackend = selectedBackend
    || snapshot.selectedBackend
    || snapshot.connections.find((c) => c.selected)?.id
    || "";
  const activeConnection = snapshot.connections.find((c) => c.id === effectiveBackend);
  const noProviderSelected = snapshot.connection !== "loading"
    && !effectiveBackend
    && !snapshot.connections.some((c) => c.selected);
  const providerBlocked = Boolean(activeConnection && isBlockingState(activeConnection.state));
  const cannotSend = noProviderSelected || providerBlocked;
  const providerNotice = noProviderSelected
    ? "No AI provider is selected yet."
    : providerBlocked
      ? activeConnection?.detail || `${activeConnection?.name || "This provider"} is unavailable.`
      : "";

  useEffect(() => {
    const openedDifferentSession = Boolean(
      currentSession?.id && backendSessionId.current !== currentSession.id,
    );
    if (openedDifferentSession) {
      backendSessionId.current = currentSession?.id || "";
      if (currentSession?.backendId) setSelectedBackend(currentSession.backendId);
    } else if (!selectedBackend) {
      const elected = currentSession?.backendId
        || snapshot.connections.find((c) => c.selected)?.id
        || snapshot.selectedBackend
        || "";
      if (elected) {
        setSelectedBackend(elected);
      } else {
        aresApi.getAresBackend().then((res) => {
          if (res.current) setSelectedBackend(res.current);
        }).catch(() => undefined);
      }
    }
    // Session workspace is the agent's working folder unless user overrides.
    if (currentSession?.workspace) setWorkspaceOverride("");
    if (currentSession?.model) {
      setSelectedModel(currentSession.model);
      setSelectedModelProvider(currentSession.provider || "");
    }
    // Restore personality from session, or fall back to onboarding character
    if (currentSession?.personality) {
      setSelectedPersonality(currentSession.personality);
    }
  }, [currentSession?.id, currentSession?.backendId, currentSession?.workspace, currentSession?.model, currentSession?.provider, currentSession?.personality, selectedBackend, snapshot.connections, snapshot.selectedBackend]);

  useEffect(() => {
    const el = transcriptRef.current;
    if (!el) return;
    if (!autoFollow) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom || streamText) el.scrollTo({ top: el.scrollHeight, behavior: streamText ? "auto" : "smooth" });
  }, [currentSession?.messages.length, streamText, streamReasoning, streamTools, streamState, autoFollow]);

  const onScroll = useCallback(() => {
    const el = transcriptRef.current;
    if (!el) return;
    setShowScrollBottom(el.scrollHeight - el.scrollTop - el.clientHeight > 120);
  }, []);

  // Dictation handling
  const toggleDictation = useCallback(() => {
    if (isListening) {
      if (recognitionRef.current) recognitionRef.current.stop();
      setIsListening(false);
      return;
    }

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Browser speech recognition is not supported in this browser.");
      return;
    }

    try {
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-US";

      recognition.onresult = (event: any) => {
        let transcriptText = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          transcriptText += event.results[i][0].transcript;
        }
        setDraft((prev) => prev + (prev ? " " : "") + transcriptText);
      };

      recognition.onerror = () => setIsListening(false);
      recognition.onend = () => setIsListening(false);

      recognition.start();
      recognitionRef.current = recognition;
      setIsListening(true);
    } catch {
      setIsListening(false);
    }
  }, [isListening]);

  // Drag & drop handlers (donor: index.html:585-590, ui.js dragover logic)
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.types.includes('Files')) {
      setIsDragOver(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // Only hide if leaving the composer area entirely
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      setAttachedFiles((prev) => [...prev, ...files]);
    }
  }, []);

  const removeAttachedFile = useCallback((index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const submit = useCallback(async (event: FormEvent) => {
    event.preventDefault();
    const message = draft.trim();
    if (!message && attachedFiles.length === 0) return;
    if (isBusy || isReadOnlyCli || cannotSend) return;

    const files = attachedFiles.length > 0 ? [...attachedFiles] : undefined;

    setDraft("");
    setAttachedFiles([]);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    const workspace =
      workspaceOverride.trim()
      || currentSession?.workspace
      || snapshot.workspaces?.[0]?.path
      || undefined;
    void sendMessage(message, {
      backendId: effectiveBackend || selectedBackend || undefined,
      model: selectedModel || undefined,
      provider: selectedModelProvider || undefined,
      workspace,
      files,
      personality: selectedPersonality || undefined,
    });
  }, [
    draft, attachedFiles, isBusy, isReadOnlyCli, cannotSend, sendMessage, selectedBackend, effectiveBackend,
    selectedModel, selectedModelProvider, workspaceOverride, currentSession, snapshot.workspaces, selectedPersonality,
  ]);

  // Suggest a connected backend when send is blocked or nothing is elected yet
  const suggestedBackend = useMemo(() => {
    if (effectiveBackend && !cannotSend) return null;
    const connected = snapshot.connections.find((c) => c.state === "connected" || c.state === "needs_attention");
    if (connected && connected.id !== effectiveBackend) return connected;
    if (!effectiveBackend) return connected || null;
    return null;
  }, [effectiveBackend, cannotSend, snapshot.connections]);

  // Persist backend selection through the session-scoped endpoint
  const selectBackend = useCallback(async (id: string) => {
    try {
      setSelectedBackend(id);
      // Auto-default to "auto" model when switching to Jaeger AI (no local GGUFs required)
      const connection = snapshot.connections.find(c => c.id === id);
      if (connection?.name.toLowerCase().includes("jaeger")) {
        setSelectedModel("auto");
        setSelectedModelProvider("");
      }
      if (currentSession?.id) {
        await aresApi.setDefaultBackend(id, currentSession.id);
      } else {
        await aresApi.setDefaultBackend(id);
      }
      await refresh();
    } catch (error) {
      console.error("Failed to set backend:", error);
    }
  }, [currentSession?.id, refresh]);

  const handleComposerKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
      const wantsSend =
        sendKey === "enter"
          ? !event.shiftKey && !event.ctrlKey && !event.metaKey
          : sendKey === "ctrl+enter"
            ? event.ctrlKey || event.metaKey
            : event.shiftKey; // shift+enter
      if (!wantsSend) return;
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    },
    [sendKey],
  );

  const copyLastResponse = useCallback(async () => {
    const lastAssistant = [...(currentSession?.messages || [])].reverse().find((m) => m.role !== "user")?.text;
    const text = streamText || lastAssistant;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (copiedTimer.current !== undefined) window.clearTimeout(copiedTimer.current);
      copiedTimer.current = window.setTimeout(() => setCopied(false), 1600);
    } catch (reason) { console.error(reason); }
  }, [currentSession?.messages, streamText]);

  const lastAssistantText = useMemo(() => {
    if (streamText) return streamText;
    return [...(currentSession?.messages || [])].reverse().find((m) => m.role !== "user")?.text;
  }, [currentSession?.messages, streamText]);

  // Agent working folder: session workspace > override > first known workspace.
  const workspacePath =
    workspaceOverride.trim()
    || currentSession?.workspace
    || snapshot.workspaces?.[0]?.path
    || "";
  const activeWorkspaceLabel = (() => {
    if (!workspacePath) return "Working folder";
    if (workspacePath === "~" || workspacePath === "/") return workspacePath;
    const segments = workspacePath.replace(/\/+$/, "").split("/").filter(Boolean);
    return segments[segments.length - 1] || workspacePath;
  })();

  // Live backends: only available connections / detected adapters.
  const backendOptions = useMemo(() => {
    const fromConnections = snapshot.connections
      .filter((c) => c.available !== false && c.state !== "offline")
      .map((c) => ({
        id: c.id,
        label: c.name || c.id,
        detail: c.detail || c.kind,
        available: Boolean(c.available),
      }));
    if (fromConnections.length) return fromConnections;
    return discoveredBackends
      .filter((b) => b.detected)
      .map((b) => ({
        id: b.adapter_id,
        label: b.display_name || b.adapter_id,
        detail: b.adapter_id,
        available: true,
      }));
  }, [snapshot.connections, discoveredBackends]);

  const activeBackendMeta = backendOptions.find((b) => b.id === effectiveBackend)
    || backendOptions.find((b) => b.id === snapshot.connections.find((c) => c.selected)?.id);
  const activeBackendLabel = activeBackendMeta?.label
    || activeConnection?.name
    || (effectiveBackend ? effectiveBackend.replace(/_/g, " ") : "Select backend");

  // Models from page-local catalog, with snapshot.backends fallback so the chip
  // works before /api/backends finishes (and when local selectedBackend was empty).
  const modelsForBackend = useMemo(() => {
    type M = { id: string; label?: string; location?: string; in_use?: boolean; provider?: string | null; notes?: string | null; available?: boolean };
    const fromPage = backendCatalog.find((b) => b.id === effectiveBackend);
    const fromSnap = (snapshot.backends || []).find((b) => b.id === effectiveBackend) as
      | { inventory?: { models?: M[] }; models?: M[] }
      | undefined;
    const listed = (
      fromPage?.inventory?.models
      || fromSnap?.inventory?.models
      || fromSnap?.models
      || []
    ).filter((m) => {
      if (!m.id || m.id.startsWith("(")) return false;
      if (m.id.includes("{") || m.id.includes("'default'")) return false;
      return true;
    });
    const rank = (m: M) =>
      (m.in_use ? 0 : 10) + (m.location === "local" ? 0 : m.location === "cloud" ? 1 : 2);
    return [...listed].sort((a, b) => rank(a) - rank(b) || a.id.localeCompare(b.id));
  }, [backendCatalog, effectiveBackend, snapshot.backends]);

  const providersForBackend = useMemo(() => {
    const entry = backendCatalog.find((b) => b.id === effectiveBackend);
    return entry?.inventory?.providers || [];
  }, [backendCatalog, effectiveBackend]);

  // When backend or catalog changes, keep model valid for that backend only.
  useEffect(() => {
    if (!effectiveBackend) return;
    if (selectedModel && (selectedModel === "auto" || modelsForBackend.some((m) => m.id === selectedModel))) return;
    const preferred = modelsForBackend.find((m) => m.in_use) || modelsForBackend[0];
    if (preferred) {
      setSelectedModel(preferred.id);
      setSelectedModelProvider(preferred.provider || "");
    } else {
      setSelectedModel("");
      setSelectedModelProvider("");
    }
  }, [effectiveBackend, modelsForBackend, selectedModel]);

  // Poll provider status every 10 seconds while chatting to detect outages
  useEffect(() => {
    if (streamState !== "streaming" && streamState !== "starting") {
      return; // Only poll while actively chatting
    }

    const pollInterval = setInterval(() => {
      refresh().catch(() => {
        // Silent catch — refresh errors are logged server-side
      });
    }, 10000); // Poll every 10 seconds

    return () => clearInterval(pollInterval);
  }, [streamState, refresh]);

  const activeModelLabel = (() => {
    if (!selectedModel) return modelsForBackend.length ? "Pick model" : "No models";
    const hit = modelsForBackend.find((m) => m.id === selectedModel);
    if (!hit) return selectedModel;
    const loc = hit.location && hit.location !== "unknown" ? ` · ${hit.location}` : "";
    return `${hit.label || hit.id}${loc}`;
  })();

  const filteredBackends = useMemo(() => {
    const q = backendSearchQuery.trim().toLowerCase();
    if (!q) return backendOptions;
    return backendOptions.filter(
      (b) => b.label.toLowerCase().includes(q) || b.id.toLowerCase().includes(q),
    );
  }, [backendOptions, backendSearchQuery]);

  const workspaceChoices = useMemo(() => {
    const paths = new Map<string, string>();
    for (const w of snapshot.workspaces || []) {
      if (w.path) paths.set(w.path, w.label || w.path);
    }
    if (currentSession?.workspace) {
      paths.set(currentSession.workspace, currentSession.workspace);
    }
    return Array.from(paths.entries()).map(([path, label]) => ({ path, label }));
  }, [snapshot.workspaces, currentSession?.workspace]);

  return (
    <div
      className="conversation-page"
      style={{ background: H.bg, color: H.text }}
    >

      {/* Hidden file input for Attach button — accepts images and other files */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="image/*,.pdf,.txt,.py,.js,.ts,.tsx,.md,.json,.yaml,.csv"
        style={{ display: "none" }}
        onChange={(e) => {
          if (e.target.files) {
            const files = Array.from(e.target.files);
            setAttachedFiles((prev) => [...prev, ...files]);
          }
        }}
      />

      {/* Messages area */}
      <div ref={transcriptRef} onScroll={onScroll} style={{ flex: 1, overflowY: "auto", overflowX: "hidden", position: "relative" }}>
        {sessionLoading ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100%", gap: "0.75rem", color: H.muted }}>
            <LoaderCircle size={22} style={{ color: H.accentGlow }} className="animate-spin" />
            <p style={{ fontSize: "0.8125rem", margin: "0rem" }}>Loading conversation…</p>
          </div>
        ) : !hasConversation ? (
          /* Empty state */
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100%", padding: "2.5rem 1.5rem", textAlign: "center", background: `radial-gradient(ellipse at 50% 25%, rgba(56,137,253,0.06) 0%, transparent 60%)` }}>
            <div style={{ marginBottom: "1.25rem" }}><SpartanHelmetSVG /></div>
            <h2 style={{ fontSize: "1.375rem", fontWeight: 700, color: H.strong, margin: "0rem" }}>What are we working on?</h2>
            <p style={{ fontSize: "0.875rem", color: H.muted, margin: "0.5rem 0 1.75rem", lineHeight: 1.6, maxWidth: "23.75rem" }}>
              {effectiveBackend
                ? `Talking to ${activeBackendLabel}. Start a session or ask anything.`
                : "Start a session, pick a backend, or ask anything."}
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", width: "100%", maxWidth: "32.5rem" }}>
              {!hideSuggestions && [
                { icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>, text: "What files are in this workspace?" },
                { icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><line x1="9" y1="12" x2="15" y2="12"/><line x1="9" y1="16" x2="12" y2="16"/></svg>, text: "What's on my schedule today?" },
                { icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></svg>, text: "Help me plan a small project." },
              ].map((s) => (
                <button key={s.text} type="button" onClick={() => { setDraft(s.text); textareaRef.current?.focus(); }}
                  style={{ display: "flex", alignItems: "center", gap: "0.75rem", padding: "0.6875rem 1rem", borderRadius: "0.625rem", border: `1px solid ${H.border2}`, background: H.surface, color: H.text, fontSize: "0.875rem", textAlign: "left", cursor: "pointer", transition: "all 0.15s" }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = H.surfaceHover; e.currentTarget.style.borderColor = H.accent + "55"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = H.surface; e.currentTarget.style.borderColor = H.border2; }}>
                  <span style={{ color: H.muted, flexShrink: 0 }}>{s.icon}</span>
                  <span>{s.text}</span>
                </button>
              ))}
            </div>
            {discoveryError && <p style={{ marginTop: "1rem", fontSize: "0.75rem", color: "#fbbf24" }}>{discoveryError}</p>}
          </div>
        ) : (
          <>
            {/* Session title - visible on mobile when sidebar is closed */}
            <div className="mobile-session-header" style={{ display: "none", padding: "0.5rem 0.75rem", borderBottom: "1px solid var(--border)", background: "var(--chat-bg)" }}>
              <h1 style={{ fontSize: "0.875rem", fontWeight: 600, color: "var(--text)", margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {currentSession?.title || "Untitled Session"}
              </h1>
              <div style={{ fontSize: "0.6875rem", color: "var(--muted)", marginTop: "0.125rem" }}>
                {activeBackendLabel}
              </div>
            </div>
            {/* Messages */}
            <div className="conversation-messages">
            {(currentSession?.messages || []).map((message) => (
              <MessageItem
                key={message.id}
                id={message.id}
                role={message.role === "tool" ? "assistant" : message.role}
                text={message.text}
                reasoning={(message as any).reasoning}
                toolCalls={(message as any).tool_calls}
                model={undefined}
                isStreaming={false}
                onCopy={(text) => {
                  navigator.clipboard.writeText(text);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                }}
                onBranch={(messageId) => {
                  if (!currentSession?.id) return;
                  const msgIdx = (currentSession.messages || []).findIndex((m: any) => m.id === messageId);
                  const keepCount = msgIdx >= 0 ? msgIdx + 1 : undefined;
                  fetch("/api/session/branch", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      session_id: currentSession.id,
                      keep_count: keepCount,
                    }),
                  })
                    .then((res) => res.json())
                    .then((data) => {
                      const newId = data?.session?.id || data?.id || data?.session_id;
                      if (newId) {
                        navigate(`/chat/${newId}`);
                      }
                    })
                    .catch(console.error);
                }}
                onRetry={(messageId) => {
                  // Find the user message preceding this assistant message
                  if (!currentSession?.messages) return;
                  const msgs = currentSession.messages;
                  const targetIdx = msgs.findIndex((m: any) => m.id === messageId);
                  let userPrompt = "";
                  for (let i = targetIdx >= 0 ? targetIdx : msgs.length - 1; i >= 0; i--) {
                    if (msgs[i].role === "user") {
                      userPrompt = msgs[i].text || (msgs[i] as any).content || "";
                      break;
                    }
                  }
                  if (userPrompt) {
                    const workspace = workspaceOverride.trim() || currentSession?.workspace || snapshot.workspaces?.[0]?.path || undefined;
                    void sendMessage(userPrompt, {
                      backendId: effectiveBackend || selectedBackend || undefined,
                      model: selectedModel || undefined,
                      provider: selectedModelProvider || undefined,
                      workspace,
                      personality: selectedPersonality || undefined,
                    });
                  }
                }}
              />
            ))}
            {streamState !== "idle" && (
              <div style={{ display: "flex", width: "100%" }}>
                <div style={{ width: "1.875rem", height: "1.875rem", borderRadius: "50%", flexShrink: 0, background: H.surface, border: `1px solid ${H.border2}`, display: "flex", alignItems: "center", justifyContent: "center", marginRight: "0.625rem", marginTop: "0.125rem" }}>
                  <Bot size={14} style={{ color: H.accentGlow }} />
                </div>
                <div style={{ maxWidth: "85%", width: "100%", fontSize: "0.875rem", lineHeight: 1.6, color: H.text }}>
                  {/* Antigravity-style live activity accordion: timer, active tool steps, thinking process */}
                  <AgentActivityFeed
                    isLive={true}
                    startTime={streamStartTime}
                    reasoning={streamReasoning}
                    toolSteps={streamToolSteps}
                    toolNames={streamTools}
                  />

                  {/* Word-by-word streaming markdown output */}
                  {streamText ? (
                    <Markdown content={streamText} streaming />
                  ) : streamState === "starting" ? (
                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: "0.25rem" }}>
                      <LoaderCircle size={14} style={{ color: H.accentGlow }} className="animate-spin" />
                      <span style={{ color: H.muted, fontSize: "0.8125rem" }}>Connecting to inference engine…</span>
                    </div>
                  ) : null}
                </div>
              </div>
            )}
          </div>
          </>
        )}
      </div>

      {/* Floating scroll / copy buttons */}
      <div style={{ position: "absolute", bottom: "6.875rem", right: "1.25rem", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.375rem", pointerEvents: "none", zIndex: 10 }}>
        {showScrollBottom && (
          <button type="button" onClick={() => transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" })}
            style={{ pointerEvents: "auto", display: "flex", alignItems: "center", gap: "0.375rem", padding: "0.3125rem 0.75rem", borderRadius: "62.4375rem", border: `1px solid ${H.border2}`, background: H.surface, color: H.text, fontSize: "0.75rem", fontWeight: 500, cursor: "pointer" }}>
            <ArrowDown size={13} /> Bottom
          </button>
        )}
        {lastAssistantText && (
          <button type="button" onClick={() => void copyLastResponse()}
            style={{ pointerEvents: "auto", display: "flex", alignItems: "center", gap: "0.375rem", padding: "0.3125rem 0.75rem", borderRadius: "62.4375rem", border: `1px solid ${H.border2}`, background: H.surface, color: H.text, fontSize: "0.75rem", fontWeight: 500, cursor: "pointer" }}>
            {copied ? <Check size={13} style={{ color: "#4ade80" }} /> : <Copy size={13} />}
            {copied ? "Copied" : "Copy"}
          </button>
        )}
      </div>

      {/* COMPOSER */}
      <div className="conversation-composer" style={{ flexShrink: 0, padding: "0 1rem 0.875rem", background: H.bg, position: "relative", zIndex: 10 }}>

        {/* Approval card */}
        {showApproval && (
          <div style={{ marginBottom: "0.5rem", borderRadius: "0.75rem", border: `1px solid ${H.border2}`, background: H.surface, overflow: "hidden", boxShadow: "0 0.5rem 2rem rgba(0,0,0,0.5)", maxWidth: "46.25rem", margin: "0 auto 0.5rem" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0.5625rem 0.875rem", borderBottom: `1px solid ${H.border}` }}>
              <span style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.8125rem", fontWeight: 600, color: H.strong }}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                Approval required
              </span>
              <div style={{ display: "flex", gap: "0.25rem" }}>
                <button onClick={() => setApprovalCollapsed(!approvalCollapsed)} style={{ background: "transparent", border: "none", color: H.muted, cursor: "pointer", padding: "0.25rem" }}>{approvalCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}</button>
                <button onClick={() => setShowApproval(false)} style={{ background: "transparent", border: "none", color: H.muted, cursor: "pointer", padding: "0.25rem" }}><X size={14} /></button>
              </div>
            </div>
            {!approvalCollapsed && (
              <div style={{ padding: "0.75rem 0.875rem" }}>
                <p style={{ fontSize: "0.8125rem", color: H.muted, marginBottom: "0.625rem" }}>Agent is requesting permission to execute:</p>
                <code style={{ display: "block", background: "#0a0c14", padding: "0.5rem 0.75rem", borderRadius: "0.4375rem", fontFamily: "monospace", fontSize: "0.75rem", color: "#4ade80", border: `1px solid ${H.border}`, marginBottom: "0.75rem", overflowX: "auto" }}>$ rm -rf /tmp/cache/*</code>
                <div style={{ display: "flex", gap: "0.375rem", flexWrap: "wrap" }}>
                  {["Allow once", "Allow session", "Always allow", "Deny", "Skip all ⚡"].map((label) => (
                    <button key={label} type="button" onClick={() => setShowApproval(false)}
                      style={{ padding: "0.3125rem 0.75rem", borderRadius: "0.4375rem", fontSize: "0.75rem", cursor: "pointer", fontWeight: 500, background: label === "Allow once" ? H.accent : label === "Deny" ? "#3b1219" : H.surface, color: label === "Allow once" ? "#fff" : label === "Deny" ? "#fca5a5" : H.text, border: label === "Allow once" ? "none" : label === "Deny" ? "1px solid #7f1d1d" : `1px solid ${H.border2}` }}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {isReadOnlyCli && (
          <div style={{ marginBottom: "0.5rem", maxWidth: "46.25rem", margin: "0 auto 0.5rem", padding: "0.5625rem 0.875rem", borderRadius: "0.5rem", border: "1px solid rgba(56,137,253,0.35)", background: "rgba(56,137,253,0.08)", color: H.accentBlue, fontSize: "0.75rem" }}>
            CLI / imported session (read-only). Switch to a <strong>WebUI</strong> session in the deck to talk to a backend.
          </div>
        )}

        {!isReadOnlyCli && cannotSend && (
          <div style={{ marginBottom: "0.5rem", maxWidth: "46.25rem", margin: "0 auto 0.5rem", padding: "0.5625rem 0.875rem", borderRadius: "0.5rem", border: "1px solid rgba(251,191,36,0.3)", background: "rgba(251,191,36,0.08)", color: "#fbbf24", fontSize: "0.8125rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <AlertTriangle size={13} style={{ flexShrink: 0 }} />
            <span style={{ flex: 1 }}>{providerNotice}</span>
            <Link
              to="/control?tab=workers&view=connections"
              style={{ flexShrink: 0, color: "#fbbf24", fontWeight: 600, textDecoration: "underline" }}
            >
              {noProviderSelected ? "Choose a provider" : "Open Connections"}
            </Link>
          </div>
        )}

        {suggestedBackend && (
          <div style={{ marginBottom: "0.5rem", maxWidth: "46.25rem", margin: "0 auto 0.5rem", padding: "0.5625rem 0.875rem", borderRadius: "0.5rem", border: `1px solid ${H.border2}`, background: `rgba(8,235,241,0.05)`, color: H.text, fontSize: "0.8125rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ flex: 1 }}>
              Suggested: <strong>{backendLabel(suggestedBackend.id)}</strong>
            </span>
            <button
              type="button"
              onClick={() => selectBackend(suggestedBackend.id)}
              style={{ flexShrink: 0, padding: "0.25rem 0.625rem", borderRadius: "0.375rem", border: "none", background: H.accentGlow, color: "#000", fontWeight: 600, cursor: "pointer", fontSize: "0.75rem" }}
            >
              Use this
            </button>
          </div>
        )}

        {chatNotice && (
          <div style={{ marginBottom: "0.5rem", maxWidth: "46.25rem", margin: "0 auto 0.5rem", padding: "0.5625rem 0.875rem", borderRadius: "0.5rem", border: "1px solid rgba(251,191,36,0.3)", background: "rgba(251,191,36,0.08)", color: "#fbbf24", fontSize: "0.8125rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <AlertTriangle size={13} style={{ flexShrink: 0 }} />
            <span style={{ flex: 1 }}>{chatNotice}</span>
            {/* A provider problem is fixed on the Connections page, so link there
                rather than leaving the user to find it. */}
            {chatNoticeProvider && PROVIDER_UNAVAILABLE_CODES.has(chatNoticeProvider.code || "") && (
              <Link
                to="/control?tab=workers&view=connections"
                style={{ flexShrink: 0, color: "#fbbf24", fontWeight: 600, textDecoration: "underline" }}
              >
                Open Connections
              </Link>
            )}
          </div>
        )}

        {/* Saved Prompts Popover */}
        {showSavedPrompts && (
          <div style={{ maxWidth: "46.25rem", margin: "0 auto 0.5rem", padding: "0.625rem", borderRadius: "0.625rem", border: `1px solid ${H.border2}`, background: H.surface, boxShadow: "0 0.5rem 1.5rem rgba(0,0,0,0.4)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.375rem", paddingBottom: "0.25rem", borderBottom: `1px solid ${H.border}` }}>
              <span style={{ fontSize: "0.75rem", fontWeight: 600, color: H.text }}>Saved Prompts</span>
              <button type="button" onClick={() => setShowSavedPrompts(false)} style={{ background: "transparent", border: "none", color: H.muted, cursor: "pointer" }}><X size={12} /></button>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.375rem" }}>
              {SAVED_PROMPT_TEMPLATES.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => {
                    setDraft((prev) => prev ? `${prev}\n\n${item.prompt}` : item.prompt);
                    setShowSavedPrompts(false);
                    textareaRef.current?.focus();
                  }}
                  style={{ textAlign: "left", padding: "0.375rem 0.5rem", borderRadius: "0.375rem", border: `1px solid ${H.border2}`, background: H.chipBg, color: H.text, fontSize: "0.6875rem", cursor: "pointer" }}
                >
                  <div style={{ fontWeight: 600, color: H.accentGlow }}>{item.label}</div>
                  <div style={{ color: H.muted, fontSize: "0.625rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.prompt}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        <form onSubmit={(e) => void submit(e)} style={{ maxWidth: "min(46.25rem, 100%)", margin: "0 auto" }}>
          {/* Fit-based footer collapse observer (donor: _fitComposerFooter) */}
          <div style={{ borderRadius: "0.875rem", border: `1px solid ${H.inputBorder}`, background: H.inputBg, boxShadow: "0 0.125rem 1rem rgba(0,0,0,0.35)", transition: "border-color 0.2s" }}>

            {/* Attached files tray */}
            {attachedFiles.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.375rem", padding: "0.5rem 0.75rem 0" }}>
                {attachedFiles.map((file, idx) => {
                  const isImg = file.type.startsWith("image/") || file.name.match(/\.(png|jpe?g|gif|webp|bmp)$/i);
                  return (
                    <span key={idx} style={{ display: "inline-flex", alignItems: "center", gap: "0.375rem", padding: "0.1875rem 0.5rem", borderRadius: "0.375rem", background: H.surface, border: `1px solid ${H.border2}`, fontSize: "0.6875rem", color: H.text }}>
                      {isImg ? (
                        <img
                          src={URL.createObjectURL(file)}
                          alt={file.name}
                          style={{ width: "1.25rem", height: "1.25rem", borderRadius: "0.25rem", objectFit: "cover", flexShrink: 0 }}
                        />
                      ) : (
                        <FileText size={11} style={{ color: H.accentGlow }} />
                      )}
                      <span style={{ maxWidth: "7.5rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{file.name}</span>
                      <button type="button" onClick={() => setAttachedFiles((prev) => prev.filter((_, i) => i !== idx))} style={{ background: "transparent", border: "none", color: H.muted, cursor: "pointer", padding: "0rem" }}>
                        <X size={10} />
                      </button>
                    </span>
                  );
                })}
              </div>
            )}

            {/* Listening indicator */}
            {isListening && (
              <div style={{ padding: "0.375rem 0.875rem", fontSize: "0.6875rem", fontWeight: 600, color: "#f43f5e", display: "flex", alignItems: "center", gap: "0.375rem" }}>
                <span style={{ width: "0.375rem", height: "0.375rem", borderRadius: "50%", background: "#f43f5e", display: "inline-block" }} />
                Listening for speech dictation…
              </div>
            )}

            <textarea
              ref={textareaRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleComposerKeyDown}
              rows={1}
              aria-label="Message"
              placeholder={
                isReadOnlyCli
                  ? "CLI session is read-only — start a new session to chat"
                  : noProviderSelected
                    ? "Choose an AI provider to start chatting"
                    : providerBlocked
                      ? `${activeConnection?.name || "This provider"} is unavailable`
                      : `Message ${activeBackendLabel}…`
              }
              disabled={isBusy || isReadOnlyCli || cannotSend}
              style={{ width: "100%", padding: "0.8125rem 1rem 0.5rem", background: "transparent", border: "none", outline: "none", color: H.text, fontSize: "0.9062rem", lineHeight: 1.5, resize: "none", fontFamily: "inherit", boxSizing: "border-box", maxHeight: "11.25rem", overflowY: "auto" }}
              onInput={(e) => { const el = e.currentTarget; el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 180) + "px"; }}
            />

            {/* Toolbar — responsive flex container bounded within chat box */}
            <div className="conversation-toolbar conversation-toolbar-simplified composer-toolbar-container" style={{ display: "flex", alignItems: "center", padding: "0.25rem 0.5rem 0.5rem", gap: "0.25rem", overflow: "visible", whiteSpace: "nowrap", maxWidth: "100%", boxSizing: "border-box" }}>
              <IconBtn title="Attach files" onClick={() => fileInputRef.current?.click()}><Paperclip size={15} /></IconBtn>
              <IconBtn title="Saved prompts" onClick={() => setShowSavedPrompts(!showSavedPrompts)}><Bookmark size={15} /></IconBtn>
              <IconBtn title="Dictate" onClick={toggleDictation}>
                {isListening ? <MicOff size={15} style={{ color: "#f43f5e" }} /> : <Mic size={15} />}
              </IconBtn>

              <div style={{ width: "0.0625rem", height: "1rem", background: H.border2, margin: "0 0.1875rem", flexShrink: 0 }} />

              {/* Active execution backend */}
              <div className="toolbar-advanced" style={{ display: "contents" }}>
                <div
                  ref={backendTriggerRef}
                  data-menu-wrapper
                  style={{ position: "relative", flexShrink: 1, minWidth: 0 }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <Chip
                    icon={<Boxes size={11} />}
                    label={activeBackendLabel}
                    title={`Agent backend: ${activeBackendLabel}`}
                    ledColor={providerBlocked ? "amber" : "emerald"}
                    onClick={() => {
                      setShowBackendMenu(!showBackendMenu);
                      setShowWorkspaceMenu(false);
                      setShowModelMenu(false);
                      setShowReasoningMenu(false);
                      setShowToolsetMenu(false);
                      setShowMobileOverflow(false);
                    }}
                  />
                  <ComposerPopover
                    isOpen={showBackendMenu}
                    onClose={() => setShowBackendMenu(false)}
                    anchorRef={backendTriggerRef}
                    width="20rem"
                  >
                    <div style={{ padding: "0.625rem 0.875rem 0.375rem", fontSize: "0.6875rem", fontWeight: 600, color: H.muted, borderBottom: `1px solid ${H.border}` }}>
                      Agent backend
                    </div>
                    <div style={{ padding: "0.5rem 0.625rem", maxHeight: "18rem", overflowY: "auto" }}>
                      {filteredBackends.map((backend) => (
                        <button
                          key={backend.id}
                          type="button"
                          onClick={() => {
                            selectBackend(backend.id);
                            setShowBackendMenu(false);
                          }}
                          style={{
                            display: "flex", alignItems: "center", gap: "0.5rem", width: "100%", padding: "0.5rem 0.625rem", marginBottom: "0.25rem",
                            borderRadius: "0.375rem", border: `1px solid ${effectiveBackend === backend.id ? H.accentGlow : H.border}`,
                            background: effectiveBackend === backend.id ? "rgba(8,235,241,0.1)" : "transparent",
                            color: H.text, textAlign: "left", cursor: "pointer",
                          }}
                        >
                          <div>
                            <div style={{ fontWeight: 600, fontSize: "0.75rem" }}>{backend.label}</div>
                            <div style={{ fontSize: "0.625rem", color: H.muted, lineHeight: 1.4 }}>{backend.detail}</div>
                          </div>
                          {effectiveBackend === backend.id && <Check size={11} style={{ marginLeft: "auto", color: H.accentGlow }} />}
                        </button>
                      ))}
                    </div>
                  </ComposerPopover>
                </div>
              </div>

              {/* Working folder */}
              <div className="toolbar-advanced" style={{ display: "contents" }}>
                <div
                  ref={workspaceTriggerRef}
                  data-menu-wrapper
                  style={{ position: "relative", display: "inline-flex", alignItems: "center", flexShrink: 1, minWidth: 0 }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="composer-workspace-group">
                    <button
                      type="button"
                      className="composer-workspace-files-btn"
                      title="Browse files in working folder (Toggles Right Workspace Panel)"
                      onClick={workbenchPanel.toggle}
                    >
                      <Folder size={11} />
                    </button>

                    <button
                      type="button"
                      title={workspacePath || "Working folder"}
                      onClick={() => {
                        setShowWorkspaceMenu(!showWorkspaceMenu);
                        setShowBackendMenu(false);
                        setShowModelMenu(false);
                        setShowReasoningMenu(false);
                        setShowToolsetMenu(false);
                        setShowMobileOverflow(false);
                      }}
                      className="composer-workspace-chip-btn"
                    >
                      <SwitchboardLED active={true} color="purple" title="Workspace context active" />
                      <span className="composer-chip__label">{activeWorkspaceLabel}</span>
                      <ChevronDown size={9} className="composer-chip__chevron" />
                    </button>
                  </div>

                  <ComposerPopover
                    isOpen={showWorkspaceMenu}
                    onClose={() => setShowWorkspaceMenu(false)}
                    anchorRef={workspaceTriggerRef}
                    width="22.5rem"
                  >
                    <div style={{ padding: "0.625rem 0.875rem 0.375rem", fontSize: "0.6875rem", fontWeight: 600, color: H.muted, borderBottom: `1px solid ${H.border}` }}>
                      Agent working folder (cwd / context)
                    </div>
                    <div style={{ padding: "0.75rem 0.875rem", background: "rgba(124,58,237,0.12)", borderBottom: `1px solid ${H.border}` }}>
                      <div style={{ fontWeight: 600, color: H.strong, fontSize: "0.8125rem", marginBottom: "0.125rem" }}>{activeWorkspaceLabel}</div>
                      <div style={{ fontSize: "0.6875rem", color: H.muted, fontFamily: "monospace", wordBreak: "break-all" }}>
                        {workspacePath || "No working folder set"}
                      </div>
                    </div>
                    <div style={{ padding: "0.5rem 0.625rem", borderBottom: `1px solid ${H.border}` }}>
                      <input
                        type="text"
                        value={wsSearchQuery}
                        onChange={(e) => setWsSearchQuery(e.target.value)}
                        placeholder="Filter known folders…"
                        style={{ width: "100%", boxSizing: "border-box", background: "#0c0e18", border: `1px solid ${H.border}`, borderRadius: "0.5rem", padding: "0.375rem 0.625rem", color: H.text, fontSize: "0.75rem", outline: "none" }}
                      />
                    </div>
                    <div style={{ maxHeight: "10rem", overflowY: "auto", padding: "0.375rem 0.5rem" }}>
                      {workspaceChoices
                        .filter((w) => {
                          const q = wsSearchQuery.trim().toLowerCase();
                          if (!q) return true;
                          return w.path.toLowerCase().includes(q) || w.label.toLowerCase().includes(q);
                        })
                        .map((w) => (
                          <button
                            key={w.path}
                            type="button"
                            onClick={() => {
                              setWorkspaceOverride(w.path);
                              setShowWorkspaceMenu(false);
                            }}
                            style={{
                              display: "block", width: "100%", textAlign: "left", padding: "0.5rem 0.625rem", marginBottom: "0.25rem",
                              borderRadius: "0.375rem", border: `1px solid ${workspacePath === w.path ? H.accent : H.border}`,
                              background: workspacePath === w.path ? "rgba(124,58,237,0.1)" : "transparent",
                              color: H.text, cursor: "pointer",
                            }}
                          >
                            <div style={{ fontWeight: 600, fontSize: "0.75rem" }}>{w.label.split("/").filter(Boolean).pop() || w.label}</div>
                            <div style={{ fontSize: "0.625rem", color: H.muted, fontFamily: "monospace", wordBreak: "break-all" }}>{w.path}</div>
                          </button>
                        ))}
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", borderTop: `1px solid ${H.border}` }}>
                      <button
                        type="button"
                        onClick={() => {
                          const path = prompt("Working folder for this agent:", workspacePath || "");
                          if (path?.trim()) setWorkspaceOverride(path.trim());
                          setShowWorkspaceMenu(false);
                        }}
                        style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem", padding: "0.625rem 0.875rem", background: "transparent", border: "none", borderBottom: `1px solid ${H.border}`, color: H.text, textAlign: "left", cursor: "pointer" }}
                      >
                        <Folder size={16} style={{ color: H.accentGlow, marginTop: "0.125rem", flexShrink: 0 }} />
                        <div>
                          <div style={{ fontWeight: 600, fontSize: "0.7812rem", color: H.strong }}>Set working folder…</div>
                          <div style={{ fontSize: "0.6875rem", color: H.muted, marginTop: "0.125rem" }}>cwd / project context for the backend</div>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          void createSession(workspacePath || undefined);
                          setShowWorkspaceMenu(false);
                        }}
                        style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem", padding: "0.625rem 0.875rem", background: "transparent", border: "none", borderBottom: `1px solid ${H.border}`, color: H.text, textAlign: "left", cursor: "pointer" }}
                      >
                        <GitBranch size={16} style={{ color: H.accentGlow, marginTop: "0.125rem", flexShrink: 0 }} />
                        <div>
                          <div style={{ fontWeight: 600, fontSize: "0.7812rem", color: H.strong }}>New project here</div>
                          <div style={{ fontSize: "0.6875rem", color: H.muted, marginTop: "0.125rem" }}>Fresh session in this folder</div>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          workbenchPanel.toggle();
                          setShowWorkspaceMenu(false);
                        }}
                        style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem", padding: "0.625rem 0.875rem", background: "transparent", border: "none", color: H.text, textAlign: "left", cursor: "pointer" }}
                      >
                        <Settings size={16} style={{ color: H.muted, marginTop: "0.125rem", flexShrink: 0 }} />
                        <div>
                          <div style={{ fontWeight: 600, fontSize: "0.7812rem", color: H.strong }}>Browse files</div>
                          <div style={{ fontSize: "0.6875rem", color: H.muted, marginTop: "0.125rem" }}>Open Right Workspace Panel</div>
                        </div>
                      </button>
                    </div>
                  </ComposerPopover>
                </div>
              </div>

              {/* Model chip */}
              <div className="toolbar-advanced" style={{ display: "contents" }}>
                <div
                  ref={modelTriggerRef}
                  data-menu-wrapper
                  style={{ position: "relative", flexShrink: 1, minWidth: 0 }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <Chip
                    icon={<Package size={11} />}
                    label={formatShortModelLabel(selectedModel === "auto" ? "Auto" : activeModelLabel)}
                    title={selectedModel === "auto" ? "Model: Auto (Jaeger AI chooses)" : `Model: ${activeModelLabel}`}
                    ledColor="cyan"
                    onClick={() => {
                      if (isReadOnlyCli) return;
                      setShowModelMenu(!showModelMenu);
                      setShowWorkspaceMenu(false);
                      setShowBackendMenu(false);
                      setShowReasoningMenu(false);
                      setShowToolsetMenu(false);
                      setShowMobileOverflow(false);
                    }}
                  />
                  <ComposerPopover
                    isOpen={showModelMenu && !isReadOnlyCli}
                    onClose={() => setShowModelMenu(false)}
                    anchorRef={modelTriggerRef}
                    width="22rem"
                  >
                    <div style={{ padding: "0.625rem 0.875rem 0.375rem", fontSize: "0.6875rem", fontWeight: 600, color: H.muted, borderBottom: `1px solid ${H.border}` }}>
                      Select Model Engine ({modelsForBackend.length} available)
                    </div>
                    <div style={{ padding: "0.5rem 0.625rem", borderBottom: `1px solid ${H.border}` }}>
                      <input
                        type="text"
                        value={modelSearchQuery}
                        onChange={(e) => setModelSearchQuery(e.target.value)}
                        placeholder="Search models or providers…"
                        style={{ width: "100%", boxSizing: "border-box", background: "#0c0e18", border: `1px solid ${H.border}`, borderRadius: "0.5rem", padding: "0.375rem 0.625rem", color: H.text, fontSize: "0.75rem", outline: "none" }}
                      />
                    </div>
                    {/* Default / Active model at top */}
                    {(() => {
                      const q = modelSearchQuery.trim().toLowerCase();
                      const activeModelObj = modelsForBackend.find((m) => m.in_use);
                      if (!activeModelObj || q) return null;
                      return (
                        <div style={{ padding: "0.5rem 0.625rem", borderBottom: `1px solid ${H.border}`, background: "rgba(8,235,241,0.04)" }}>
                          <div style={{ fontSize: "0.625rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: H.accentGlow, margin: "0.125rem 0.125rem 0.375rem" }}>
                            Default Configured Model
                          </div>
                          <button
                            type="button"
                            onClick={() => {
                              setSelectedModel(activeModelObj.id);
                              setSelectedModelProvider(activeModelObj.provider || "");
                              setShowModelMenu(false);
                            }}
                            style={{
                              display: "flex", alignItems: "center", gap: "0.5rem", width: "100%", padding: "0.5rem 0.625rem",
                              borderRadius: "0.375rem", border: `1px solid ${selectedModel === activeModelObj.id ? H.accentGlow : H.border}`,
                              background: selectedModel === activeModelObj.id ? "rgba(8,235,241,0.12)" : "transparent", color: H.text, cursor: "pointer", textAlign: "left",
                            }}
                          >
                            <div>
                              <div style={{ fontWeight: 600, fontSize: "0.75rem", display: "inline-flex", alignItems: "center", gap: "0.375rem" }}>
                                <Package size={11} style={{ color: H.accentGlow }} />
                                {activeModelObj.label || activeModelObj.id}
                                <span style={{ fontSize: "0.5625rem", fontWeight: 700, padding: "1px 0.3125rem", borderRadius: "0.25rem", background: H.accentGlow, color: "#fff" }}>DEFAULT</span>
                              </div>
                              <div style={{ fontSize: "0.625rem", color: H.muted, fontFamily: "monospace" }}>
                                {activeModelObj.provider || "—"}{activeModelObj.notes ? ` · ${activeModelObj.notes}` : ""}
                              </div>
                            </div>
                            {selectedModel === activeModelObj.id && <Check size={11} style={{ marginLeft: "auto", color: H.accentGlow }} />}
                          </button>
                        </div>
                      );
                    })()}

                    {/* Auto option — Jaeger AI decides */}
                    <div style={{ padding: "0.375rem 0.625rem", borderBottom: `1px solid ${H.border}` }}>
                      <button
                        type="button"
                        onClick={() => { setSelectedModel("auto"); setSelectedModelProvider(""); setShowModelMenu(false); }}
                        style={{
                          display: "flex", alignItems: "center", gap: "0.5rem", width: "100%", padding: "0.4375rem 0.625rem",
                          borderRadius: "0.375rem", border: `1px solid ${selectedModel === "auto" ? H.accentGlow : H.border}`,
                          background: selectedModel === "auto" ? "rgba(8,235,241,0.1)" : "transparent", color: H.text, cursor: "pointer", textAlign: "left",
                        }}
                      >
                        <div>
                          <div style={{ fontWeight: 600, fontSize: "0.75rem", display: "inline-flex", alignItems: "center", gap: "0.375rem" }}>
                            <Boxes size={11} style={{ opacity: 0.7 }} />
                            Auto
                            {selectedModel === "auto" && <span style={{ fontSize: "0.5625rem", fontWeight: 700, padding: "1px 0.3125rem", borderRadius: "0.25rem", background: H.accentGlow, color: "#fff" }}>ACTIVE</span>}
                          </div>
                          <div style={{ fontSize: "0.625rem", color: H.muted }}>Jaeger AI selects the best model for your request</div>
                        </div>
                        {selectedModel === "auto" && <Check size={11} style={{ marginLeft: "auto", color: H.accentGlow }} />}
                      </button>
                    </div>

                    {/* Models grouped by configured provider with collapsible accordions */}
                    <div style={{ maxHeight: "16rem", overflowY: "auto" }}>
                      
                      {/* Custom model input (donor: ui.js:4201-4206) */}
                      <div style={{ padding: "0.5rem 0.75rem", borderBottom: `1px solid ${H.border}`, background: "rgba(255,255,255,0.02)" }}>
                        <div style={{ fontSize: "0.625rem", fontWeight: 600, color: H.muted, marginBottom: "0.375rem" }}>Custom model ID</div>
                        <div style={{ display: "flex", gap: "0.375rem" }}>
                          <input
                            type="text"
                            value={customModelId}
                            onChange={(e) => setCustomModelId(e.target.value)}
                            placeholder="e.g. openai/gpt-5.4"
                            style={{
                              flex: 1,
                              background: H.surface,
                              border: `1px solid ${H.border}`,
                              borderRadius: "6px",
                              padding: "0.375rem 0.625rem",
                              color: H.text,
                              fontSize: "0.75rem",
                              outline: "none",
                            }}
                          />
                          <button
                            type="button"
                            onClick={() => {
                              if (customModelId.trim()) {
                                setSelectedModel(customModelId.trim());
                                setSelectedModelProvider("");
                                setShowModelMenu(false);
                                setCustomModelId("");
                              }
                            }}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              justifyContent: "center",
                              width: "32px",
                              height: "32px",
                              borderRadius: "6px",
                              border: `1px solid ${H.accent}`,
                              background: H.accent,
                              color: "#fff",
                              cursor: customModelId.trim() ? "pointer" : "default",
                              opacity: customModelId.trim() ? 1 : 0.5,
                            }}
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                              <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                            </svg>
                          </button>
                        </div>
                      </div>
                      
                    {(() => {
                      const q = modelSearchQuery.trim().toLowerCase();
                      const hasActiveSearch = q.length > 0;
                      // Provider error map for health hints (donor: ui.js:4230-4235)
                      const provErrorMap: Record<string, string> = {};
                      if (discoveryError) {
                        provErrorMap["xai-oauth"] = discoveryError.toLowerCase().includes("xai") ? discoveryError : "";
                        provErrorMap["openai-codex"] = discoveryError.toLowerCase().includes("openai") ? discoveryError : "";
                        provErrorMap["ollama-cloud"] = discoveryError.toLowerCase().includes("ollama") ? discoveryError : "";
                      }
                      const formatProviderLabel = (prov: string) => {
                        if (!prov) return "Other";
                        const p = prov.toLowerCase();
                        if (p === "xai-oauth" || p === "xai") return "xAI (Grok)";
                        if (p === "openai-codex" || p === "codex") return "OpenAI Codex";
                        if (p === "anthropic") return "Anthropic (Claude)";
                        if (p === "gemini" || p === "google") return "Google Gemini";
                        if (p === "copilot") return "GitHub Copilot";
                        if (p === "ollama-cloud") return "Ollama Cloud";
                        if (p === "ollama") return "Ollama (Local)";
                        if (p === "openrouter") return "OpenRouter";
                        if (p === "huggingface") return "HuggingFace";
                        return prov;
                      };

                      const providerKeys: string[] = [];
                      for (const m of modelsForBackend) {
                        const pKey = m.provider || "other";
                        if (!providerKeys.includes(pKey)) providerKeys.push(pKey);
                      }

                      return providerKeys.map((prov) => {
                        const health = providerHealth[prov];
                        // Hide unconfigured/missing providers unless explicitly searched for
                        if (health && health.status === "missing" && !q) return null;

                        const group = modelsForBackend.filter((m) => {
                          if ((m.provider || "other") !== prov) return false;
                          if (!q) return true;
                          return m.id.toLowerCase().includes(q) || (m.label || "").toLowerCase().includes(q) || (m.provider || "").toLowerCase().includes(q);
                        });
                        if (!group.length) return null;
                        
                        // Check if this provider has the selected model (should be open by default unless user closed it)
                        const hasSelectedModel = group.some(m => m.id === selectedModel && (m.provider || "") === selectedModelProvider);
                        const isOpen = hasActiveSearch
                          ? true
                          : openGroups.has(prov)
                            ? true
                            : closedGroups.has(prov)
                              ? false
                              : hasSelectedModel;
                        const overflowThreshold = 8;
                        const showOverflow = group.length > overflowThreshold;
                        const visibleGroup = showOverflow && !isOpen ? group.slice(0, overflowThreshold) : group;
                        const hiddenCount = showOverflow && !isOpen ? group.length - overflowThreshold : 0;

                        return (
                          <div key={prov} style={{ marginBottom: "0.25rem" }}>
                            {/* Collapsible group header (donor: ui.js:4480-4515) */}
                            <button
                              type="button"
                              onClick={() => {
                                if (isOpen) {
                                  setOpenGroups((prev) => {
                                    const next = new Set(prev);
                                    next.delete(prov);
                                    return next;
                                  });
                                  setClosedGroups((prev) => new Set([...prev, prov]));
                                } else {
                                  setClosedGroups((prev) => {
                                    const next = new Set(prev);
                                    next.delete(prov);
                                    return next;
                                  });
                                  setOpenGroups((prev) => new Set([...prev, prov]));
                                }
                              }}
                              className={`model-group collapsible ${isOpen ? "open" : ""}`}
                              style={{
                                width: "100%",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                padding: "0.5rem 0.625rem",
                                background: "transparent",
                                border: "none",
                                borderBottom: `1px solid ${H.border2}`,
                                cursor: "pointer",
                                fontSize: "0.625rem",
                                fontWeight: 700,
                                textTransform: "uppercase",
                                letterSpacing: "0.08em",
                                color: H.muted,
                              }}
                            >
                              <span style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
                                <span style={{ 
                                  display: "inline-block",
                                  width: "6px",
                                  height: "6px",
                                  transform: isOpen ? "rotate(90deg)" : "rotate(0deg)",
                                  transition: "transform 0.15s ease",
                                }}>▶</span>
                                {formatProviderLabel(prov)}
                                {showOverflow && !isOpen && (
                                  <span style={{ fontSize: "0.5625rem", fontWeight: 400, opacity: 0.7 }}>({overflowThreshold} of {group.length})</span>
                                )}
                                {showOverflow && isOpen && (
                                  <span style={{ fontSize: "0.5625rem", fontWeight: 400, opacity: 0.7 }}>({group.length})</span>
                                )}
                                {!showOverflow && (
                                  <span style={{ fontSize: "0.5625rem", fontWeight: 400, opacity: 0.7 }}>({group.length})</span>
                                )}
                              </span>
                              {/* Live provider health badge + Reset ETA */}
                              {(() => {
                                if (!health) return null;
                                if (health.status === "exhausted") {
                                  return (
                                    <span 
                                      style={{ fontSize: "0.5625rem", fontWeight: 600, padding: "1px 0.375rem", borderRadius: "0.25rem", background: "rgba(249,115,22,0.15)", color: "#f97316", border: "1px solid rgba(249,115,22,0.3)" }} 
                                      title={`${prov}: ${health.details}`}
                                    >
                                      {health.reset_eta ? `⏳ ${health.reset_eta}` : "EXHAUSTED"}
                                    </span>
                                  );
                                }
                                if (health.status === "healthy") {
                                  return (
                                    <span style={{ fontSize: "0.5625rem", color: "#22c55e", opacity: 0.8 }} title={`${prov}: ${health.details}`}>
                                      ●
                                    </span>
                                  );
                                }
                                return (
                                  <span style={{ fontSize: "0.5625rem", color: "#f43f5e", opacity: 0.8 }} title={`${prov}: ${health.details}`}>
                                    ⚠
                                  </span>
                                );
                              })()}
                            </button>
                            
                            {/* Collapsible body */}
                            {isOpen && (
                              <div className="model-group-body" style={{ padding: "0.375rem 0.625rem" }}>
                                {visibleGroup.map((m) => (
                                  <button
                                    key={`${m.id}-${m.provider || ""}`}
                                    type="button"
                                    onClick={() => {
                                      setSelectedModel(m.id);
                                      setSelectedModelProvider(m.provider || "");
                                      setShowModelMenu(false);
                                    }}
                                    style={{
                                      display: "block", width: "100%", textAlign: "left", padding: "0.5rem 0.625rem", marginBottom: "0.25rem",
                                      borderRadius: "6px", border: `1px solid ${selectedModel === m.id ? H.accent : H.border}`,
                                      background: selectedModel === m.id ? "rgba(124,58,237,0.1)" : "transparent", color: H.text, cursor: "pointer",
                                    }}
                                  >
                                    {/* Two-line layout (donor: ui.js:4345-4355) */}
                                    <div style={{ fontWeight: 600, fontSize: "0.75rem", display: "inline-flex", alignItems: "center", gap: "0.375rem" }}>
                                      <Package size={11} style={{ opacity: 0.7 }} />
                                      {m.label || m.id}
                                      {m.in_use ? (
                                        <span style={{ fontSize: "0.5625rem", fontWeight: 700, padding: "1px 0.3125rem", borderRadius: "0.25rem", background: H.accent, color: "#fff" }}>DEFAULT</span>
                                      ) : null}
                                      {selectedModel === m.id && (
                                        <span style={{ fontSize: "0.5625rem", fontWeight: 700, padding: "1px 0.3125rem", borderRadius: "0.25rem", background: "rgba(124,58,237,0.2)", color: H.accent }}>SELECTED</span>
                                      )}
                                    </div>
                                    {/* Raw model ID on second line */}
                                    <div style={{ fontSize: "0.625rem", color: H.muted, fontFamily: "monospace", marginTop: "2px", opacity: 0.7 }}>
                                      {m.id}
                                    </div>
                                  </button>
                                ))}
                                
                                {/* Show More button (donor: ui.js:4240-4310) */}
                                {showOverflow && !isOpen && (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setClosedGroups((prev) => {
                                        const next = new Set(prev);
                                        next.delete(prov);
                                        return next;
                                      });
                                      setOpenGroups((prev) => new Set([...prev, prov]));
                                    }}
                                    style={{
                                      width: "100%",
                                      padding: "0.5rem",
                                      background: "transparent",
                                      border: `1px dashed ${H.border}`,
                                      borderRadius: "6px",
                                      color: H.muted,
                                      fontSize: "0.6875rem",
                                      cursor: "pointer",
                                      marginTop: "0.25rem",
                                    }}
                                  >
                                    Show {hiddenCount} more...
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      });
                    })()}
                    </div>
                  </ComposerPopover>
                </div>
              </div>

              {/* Reasoning Effort Chip (donor: ui.js:5062-5067) */}
              {(() => {
                const hasLadder = supportedEfforts.length > 0;
                const supports = hasLadder || supportsThinkingToggle;
                if (!supports) return null;
                return (
                <div className="toolbar-advanced toolbar-advanced-secondary" style={{ display: "contents" }}>
                <div
                  ref={reasoningTriggerRef}
                  data-menu-wrapper
                  style={{ position: "relative", flexShrink: 1, minWidth: 0 }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <Chip
                    icon={<Brain size={11} />}
                    label={REASONING_OPTIONS.find(o => o.value === selectedReasoning)?.label || "Medium"}
                    title={`Reasoning Effort: ${REASONING_OPTIONS.find(o => o.value === selectedReasoning)?.label || "Medium"}${Boolean(streamReasoning) ? " (AI is deep thinking...)" : ""}`}
                    maxWidth="5.5rem"
                    ledColor="purple"
                    ledPulse={Boolean(streamReasoning || (isBusy && selectedReasoning !== "none"))}
                    onClick={() => {
                      if (isReadOnlyCli) return;
                      setShowReasoningMenu(!showReasoningMenu);
                      setShowBackendMenu(false);
                      setShowModelMenu(false);
                      setShowWorkspaceMenu(false);
                      setShowToolsetMenu(false);
                      setShowMobileOverflow(false);
                    }}
                  />
                  <ComposerPopover
                    isOpen={showReasoningMenu && !isReadOnlyCli}
                    onClose={() => setShowReasoningMenu(false)}
                    anchorRef={reasoningTriggerRef}
                    width="14rem"
                    align="right"
                  >
                    <div style={{ padding: "0.625rem 0.875rem 0.375rem", fontSize: "0.6875rem", fontWeight: 600, color: H.muted, borderBottom: `1px solid ${H.border}` }}>
                      Reasoning Effort
                    </div>
                    <div style={{ padding: "0.375rem 0.5rem" }}>
                      {(() => {
                        // Dynamic reasoning options (donor: ui.js:5005-5035)
                        const hasLadder = supportedEfforts.length > 0;
                        const supports = hasLadder || supportsThinkingToggle;
                        
                        // Hide chip entirely if model supports neither (donor: ui.js:5062-5067)
                        if (!supports) {
                          return (
                            <div style={{ padding: "0.5rem 0.625rem", fontSize: "0.6875rem", color: H.muted, textAlign: "center" }}>
                              Reasoning not supported by this model
                            </div>
                          );
                        }
                        
                        // Build options: Default + Off + dynamic ladder
                        // Default and None always shown if toggle supported (donor: ui.js:5017-5024)
                        const dynamicOptions = [
                          { value: "", label: "Default" },
                          { value: "none", label: "Off" },
                          ...supportedEfforts.map((effort: string) => ({
                            value: effort,
                            label: effort.charAt(0).toUpperCase() + effort.slice(1),
                          })),
                        ];
                        
                        return dynamicOptions.map((opt) => (
                          <button
                            key={opt.value}
                            type="button"
                            onClick={() => { setSelectedReasoning(opt.value); setShowReasoningMenu(false); }}
                            style={{
                              display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", padding: "0.375rem 0.625rem", marginBottom: "0.125rem",
                              borderRadius: "0.375rem", border: `1px solid ${selectedReasoning === opt.value ? H.accentGlow : H.border}`,
                              background: selectedReasoning === opt.value ? "rgba(8,235,241,0.1)" : "transparent",
                              color: H.text, textAlign: "left", cursor: "pointer", fontSize: "0.75rem",
                            }}
                          >
                            <span style={{ fontWeight: selectedReasoning === opt.value ? 600 : 400 }}>{opt.label}</span>
                            {selectedReasoning === opt.value && <Check size={11} style={{ color: H.accentGlow }} />}
                          </button>
                        ));
                      })()}
                    </div>
                  </ComposerPopover>
                </div>
              </div>
                );
              })()}

              {/* YOLO / Auto-Approve Toggle */}
              <button
                className="toolbar-advanced-secondary"
                type="button"
                title={yoloMode ? "YOLO mode: auto-approve all tool calls" : "Manual approval: confirm each tool call"}
                onClick={() => setYoloMode(!yoloMode)}
                style={{
                  display: "inline-flex", alignItems: "center", gap: "0.25rem", height: "1.5rem", padding: "0 0.375rem",
                  borderRadius: "0.375rem", border: `1px solid ${yoloMode ? "#ef4444" : H.chipBorder}`,
                  background: yoloMode ? "rgba(239,68,68,0.12)" : H.chipBg,
                  color: yoloMode ? "#ef4444" : H.chipText, fontSize: "0.6875rem", fontWeight: 500, cursor: "pointer",
                  transition: "all 0.15s", flexShrink: 0,
                }}
              >
                <SwitchboardLED active={true} color={yoloMode ? "red" : "emerald"} title={yoloMode ? "YOLO active: Auto-approve" : "Manual confirmation"} />
                <Zap size={11} style={{ opacity: 0.8 }} />
                <span style={{ fontSize: "0.625rem" }}>YOLO</span>
              </button>

              {/* Toolsets Chip */}
              <div
                ref={toolsetTriggerRef}
                className="toolbar-advanced-secondary"
                data-menu-wrapper
                style={{ position: "relative", flexShrink: 0 }}
                onClick={(e) => e.stopPropagation()}
              >
                <Chip
                  icon={<WrenchIcon size={12} />}
                  label="Global"
                  title={streamTools.length > 0 ? "Tools executing..." : "Toolsets: Global (all enabled)"}
                  ledColor={streamTools.length > 0 ? "emerald" : "amber"}
                  ledPulse={streamTools.length > 0}
                  onClick={() => {
                    if (isReadOnlyCli) return;
                    setShowToolsetMenu(!showToolsetMenu);
                    setShowBackendMenu(false);
                    setShowModelMenu(false);
                    setShowWorkspaceMenu(false);
                    setShowReasoningMenu(false);
                    setShowMobileOverflow(false);
                  }}
                />
                <ComposerPopover
                  isOpen={showToolsetMenu && !isReadOnlyCli}
                  onClose={() => setShowToolsetMenu(false)}
                  anchorRef={toolsetTriggerRef}
                  width="16rem"
                  align="right"
                >
                  <div style={{ padding: "0.625rem 0.875rem 0.375rem", fontSize: "0.6875rem", fontWeight: 600, color: H.muted, borderBottom: `1px solid ${H.border}` }}>
                    Toolsets
                  </div>
                  <div style={{ padding: "0.75rem 0.875rem", background: "rgba(8,235,241,0.05)", borderBottom: `1px solid ${H.border}` }}>
                    <div style={{ fontWeight: 600, color: H.strong, fontSize: "0.8125rem", marginBottom: "0.125rem" }}>Global</div>
                    <div style={{ fontSize: "0.6875rem", color: H.muted, lineHeight: 1.5 }}>All available tools enabled. Select per-tool control in Settings.</div>
                  </div>
                  <div style={{ padding: "0.5rem 0.625rem", fontSize: "0.625rem", color: H.muted, lineHeight: 1.5 }}>
                    <strong>Global</strong> mode uses all tools the backend provides. Per-tool filtering is available in the Settings page.
                  </div>
                </ComposerPopover>
              </div>

              <div style={{ flex: 1, minWidth: "0.25rem" }} />

              {/* Mobile Overflow Menu Button (shows on narrow container widths) */}
              <div
                ref={mobileOverflowTriggerRef}
                className="composer-mobile-overflow-btn"
                data-menu-wrapper
                style={{ position: "relative", flexShrink: 0 }}
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  title="More chat options"
                  onClick={() => {
                    setShowMobileOverflow(!showMobileOverflow);
                    setShowBackendMenu(false);
                    setShowModelMenu(false);
                    setShowWorkspaceMenu(false);
                    setShowReasoningMenu(false);
                    setShowToolsetMenu(false);
                  }}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    width: "1.75rem",
                    height: "1.5rem",
                    borderRadius: "0.375rem",
                    border: `1px solid ${H.chipBorder}`,
                    background: H.chipBg,
                    color: H.chipText,
                    cursor: "pointer",
                  }}
                >
                  <SlidersHorizontal size={12} />
                </button>
                <ComposerPopover
                  isOpen={showMobileOverflow}
                  onClose={() => setShowMobileOverflow(false)}
                  anchorRef={mobileOverflowTriggerRef}
                  width="18rem"
                  align="right"
                >
                  <div style={{ padding: "0.625rem 0.875rem", fontWeight: 600, borderBottom: `1px solid ${H.border}`, color: H.strong, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span>Chat Controls</span>
                    <span style={{ fontSize: "0.625rem", color: H.accentGlow }}>{activeBackendLabel}</span>
                  </div>
                  <div style={{ padding: "0.5rem 0.625rem", display: "flex", flexDirection: "column", gap: "0.375rem" }}>
                    <button
                      type="button"
                      onClick={() => { setShowMobileOverflow(false); setShowBackendMenu(true); }}
                      style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0.5rem 0.625rem", borderRadius: "0.375rem", border: `1px solid ${H.border2}`, background: H.surface, color: H.text, fontSize: "0.75rem", cursor: "pointer", textAlign: "left" }}
                    >
                      <span style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
                        <Boxes size={13} style={{ color: H.accentGlow }} /> Backend
                      </span>
                      <span style={{ color: H.accentGlow, fontWeight: 600, fontSize: "0.6875rem" }}>{activeBackendLabel}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => { setShowMobileOverflow(false); setShowModelMenu(true); }}
                      style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0.5rem 0.625rem", borderRadius: "0.375rem", border: `1px solid ${H.border2}`, background: H.surface, color: H.text, fontSize: "0.75rem", cursor: "pointer", textAlign: "left" }}
                    >
                      <span style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
                        <Package size={13} style={{ color: H.accent }} /> Model
                      </span>
                      <span style={{ color: H.text, fontWeight: 500, fontSize: "0.6875rem" }}>{formatShortModelLabel(selectedModel === "auto" ? "Auto" : activeModelLabel)}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => { setShowMobileOverflow(false); setShowWorkspaceMenu(true); }}
                      style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0.5rem 0.625rem", borderRadius: "0.375rem", border: `1px solid ${H.border2}`, background: H.surface, color: H.text, fontSize: "0.75rem", cursor: "pointer", textAlign: "left" }}
                    >
                      <span style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
                        <Folder size={13} style={{ color: "#a855f7" }} /> Workspace
                      </span>
                      <span style={{ color: H.muted, fontSize: "0.6875rem", maxWidth: "8rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{activeWorkspaceLabel}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setYoloMode(!yoloMode)}
                      style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0.5rem 0.625rem", borderRadius: "0.375rem", border: `1px solid ${yoloMode ? "#ef4444" : H.border2}`, background: yoloMode ? "rgba(239,68,68,0.12)" : H.surface, color: yoloMode ? "#ef4444" : H.text, fontSize: "0.75rem", cursor: "pointer" }}
                    >
                      <span style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
                        <Zap size={13} /> YOLO Mode
                      </span>
                      <span style={{ fontWeight: 600, fontSize: "0.6875rem" }}>{yoloMode ? "ACTIVE" : "OFF"}</span>
                    </button>
                  </div>
                </ComposerPopover>
              </div>

              {/* Context token ring (donor: ui.js:6488-6508) */}
              {(() => {
                const tokens = (currentSession as any)?.last_prompt_tokens || 0;
                const limit = 128000;
                const pct = tokens > 0 ? Math.min(Math.round((tokens / limit) * 100), 100) : 0;
                const arcColor = pct <= 50 ? "#22c55e" : pct <= 85 ? "#f97316" : "#ef4444";
                const offset = 87.96 * (1 - pct / 100);
                return tokens > 0 ? (
                  <div
                    title={`Context: ${tokens.toLocaleString()} / ${limit.toLocaleString()} tokens (${pct}% used)`}
                    style={{ display: "inline-flex", alignItems: "center", cursor: "help", marginRight: "0.5rem" }}
                  >
                    <svg viewBox="0 0 36 36" width="22" height="22" style={{ transform: "rotate(-90deg)" }}>
                      <circle cx="18" cy="18" r="14" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="3.5" />
                      <circle
                        cx="18" cy="18" r="14" fill="none"
                        stroke={arcColor}
                        strokeWidth="3.5"
                        strokeDasharray="87.96 87.96"
                        strokeDashoffset={offset}
                        strokeLinecap="round"
                      />
                      <text
                        x="18" y="18" textAnchor="middle" dominantBaseline="middle"
                        style={{ transform: "rotate(90deg)", transformOrigin: "18px 18px", fontSize: "9px", fontWeight: 700, fill: arcColor, stroke: "none" }}
                      >
                        {pct}
                      </text>
                    </svg>
                  </div>
                ) : null;
              })()}
              
              {isBusy ? (
                <button type="button" onClick={() => void cancelResponse()} title="Stop response" className="conversation-stop-btn"
                  style={{ width: "2.125rem", height: "2.125rem", borderRadius: "50%", border: "none", background: "#f43f5e", color: "#ffffff", boxShadow: "0 0 12px rgba(244,63,94,0.4)", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", transition: "transform 0.15s" }}>
                  <Square size={13} fill="currentColor" />
                </button>
              ) : (
                <button type="submit" disabled={!draft.trim() && attachedFiles.length === 0} title="Send message"
                  style={{ width: "2.125rem", height: "2.125rem", borderRadius: "50%", border: "none", background: draft.trim() || attachedFiles.length > 0 ? "#e11d48" : "rgba(255,255,255,0.06)", color: draft.trim() || attachedFiles.length > 0 ? "#ffffff" : "rgba(255,255,255,0.25)", cursor: draft.trim() || attachedFiles.length > 0 ? "pointer" : "default", display: "flex", alignItems: "center", justifyContent: "center", transition: "background 0.15s, color 0.15s" }}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>
                </button>
              )}
            </div>
          </div>
        </form>
      </div>
    </div>
  );

// Fit-based composer footer collapse (donor: _fitComposerFooter in ui.js)
// Toggles stage classes: (none) → cf-icons → cf-burger based on actual overflow
useEffect(() => {
  const footer = document.querySelector('.composer-toolbar-container');
  const left = footer?.querySelector('.composer-left');
  if (!footer || !left) return;

  const checkOverflow = () => {
    if (!left.clientWidth) return;
    const overflows = left.scrollWidth > left.clientWidth + 1;
    footer.classList.remove('cf-icons', 'cf-burger');
    if (overflows) {
      footer.classList.add('cf-icons');
      // Check again in icon mode
      if (left.scrollWidth > left.clientWidth + 1) {
        footer.classList.add('cf-burger');
      }
    }
  };

  // Initial check
  checkOverflow();

  // Observe size changes
  const observer = new ResizeObserver(checkOverflow);
  observer.observe(footer);
  observer.observe(left);

  // Observe mutations (chip content changes)
  const mutationObserver = new MutationObserver(checkOverflow);
  mutationObserver.observe(left, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ['class', 'style', 'hidden'],
  });

  return () => {
    observer.disconnect();
    mutationObserver.disconnect();
  };
}, []);

}
