# ARES MCP Architecture, Servers, Tools & Capabilities Catalog

This document is the canonical, comprehensive inventory and architectural specification of all Model Context Protocol (MCP) servers, tools, API endpoints, capabilities, and client configurations across the ARES ecosystem.

---

## 1. Architectural Overview & Security Boundary

ARES enforces a **single-network-gateway architecture** with strict capability confinement:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        External MCP Clients                            │
│   (Claude Code, OpenAI Codex CLI, Gemini CLI, VS Code, Antigravity)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    │ (1) Direct stdio or
                                    │ (2) Streamable HTTP SSE (8811)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Agentgateway (Single Network Boundary :8811)              │
│               - Strict Bearer Authentication (~/.ares/gateway/*.token) │
│               - Target Federation & Tool Namespace Separation          │
└───────────────────┬────────────────────────────────┬───────────────────┘
                    │ Target: "system"               │ Target: "host-hermes"
                    ▼                                ▼
┌──────────────────────────────────────┐  ┌──────────────────────────────┐
│       ares-system (FastMCP)          │  │     ares-host (FastMCP)      │
│  Control Plane & Orchestration       │  │  Workspace & Perception      │
│  - Durable goals & agent runs        │  │  - Jailed path confinement   │
│  - System telemetry & health         │  │  - Default-deny capabilities │
│  - Consequential approvals           │  │  - Vision, Audio & Gimbal    │
└───────────────────┬──────────────────┘  └──────────────┬───────────────┘
                    │                                    │
                    ▼ HTTP Loopback                      ▼ Audit JSONL
┌──────────────────────────────────────┐  ┌──────────────────────────────┐
│      ARES Core FastAPI (:8788)       │  │  ~/.ares/audit/host-*.jsonl  │
│  - /api/mcp/catalog                  │  └──────────────────────────────┘
│  - /api/mcp/tools                    │
│  - /api/mcp/servers                  │
└──────────────────────────────────────┘
```

### Key Architectural Principles
1. **Single Governed Network Gateway**: All external network MCP traffic connects through **Agentgateway** on port `8811` (`http://127.0.0.1:8811/mcp`) using strict bearer tokens.
2. **Default-Deny Capability Gating**: Tools operating on the host (`ares-host`) verify grants from `~/.ares/capabilities/grants.json` before executing any operation.
3. **Filesystem Confinement**: Host workspace tools are strictly confined to approved roots (e.g. `~/workspace`, `~/GitHub`). Directory traversal (`..`) and symlink escapes outside the boundary are rejected with `PermissionError`.
4. **Immutable Audit Evidence**: Every host capability call logs metadata (caller, path, bytes, SHA-256, outcome) to `~/.ares/audit/host-capabilities.jsonl`. Content bodies are never logged.

---

## 2. Server Inventory

| Server ID | Transport | Entrypoint / Binary | Port / Endpoint | Tools | Primary Responsibility |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **`ares-system`** | `stdio` / Gateway | `services/controller/system_mcp_server.py` | `http://127.0.0.1:8811/mcp` (target `system`) | 9 | Control plane: goals, agent wakes, runs, metrics, approvals |
| **`ares-host`** | `stdio` / Gateway | `services/controller/host_capability_mcp_server.py` | `http://127.0.0.1:8811/mcp` (target `host-hermes`) | 23 | Identity-scoped workspace confinement, Apple tools, physical camera/mic/gimbal |
| **`ares-webui`** | `stdio` | `services/controller/mcp_server.py` | Loopback stdio | 18 | Session & project management, deep research, PDF, media, task store |
| **`ares-native-mcp`** | `stdio` / Native | `apps/macos/Sources/ARESNativeMCP/main.swift` | Native macOS helper | 12 | Apple EventKit, Contacts, Notes, ScreenCaptureKit, Spotlight, WeatherKit |
| **`jaeger-mcp-proxy`**| `stdio-bridge` | `services/controller/jaeger_mcp_proxy.py` | Loopback IPC | 23 | Direct bridge to Jaeger companion MCP tools |

---

## 3. Tool Reference by Server

### Server 1: `ares-system` (9 Tools)
Governed system automation tools exposed to authorized clients and federated via Agentgateway under `system_*`.

| Tool Name | Parameters | Capability / Scope | Description |
| :--- | :--- | :--- | :--- |
| `system_status` | *None* | Read-only | Returns safe ARES control plane state, active run count, and pending approvals. |
| `system_metrics` | `include_processes: bool = True`<br>`process_limit: int = 10` | Read-only | Telemetry for host CPU, RAM, swap, disk, Ollama, and Jaeger runner. |
| `agents_list` | *None* | Read-only | Lists registered durable agents (Hermes, JaegerAI, Admin, OpenClaw). |
| `integrations_list`| *None* | Read-only | Returns canonical client integration catalog and activation states. |
| `system_message` | `message: str`<br>`agent_id: str = "hermes"`<br>`wait_seconds: int = 0` | Orchestration | Creates a durable goal and delegates execution to Hermes or JaegerAI. |
| `run_status` | `run_id: str` | Read-only | Returns run progress and immutable evidence event stream. |
| `run_cancel` | `run_id: str` | Mutation | Safely requests cancellation of an active ARES run. |
| `approval_respond`| `approval_id: str`<br>`decision: "approved" \| "denied"` | Governance | Approves or denies a pending consequential action. |
| `approval_preview`| `approval_id: str` | Read-only | Dry-run preview of an approval request without executing. |

---

### Server 2: `ares-host` (23 Tools)
Identity-scoped host workspace and hardware perception tools. Enforces root confinement, capability grants, and audit logging.

#### Physical Perception & Hardware (Insta360 Link 2)
| Tool Name | Parameters | Required Capability | Description |
| :--- | :--- | :--- | :--- |
| `camera_status` | *None* | `camera.status` | Inspects connected camera presence, AVFoundation indices, and gimbal orientation. |
| `camera_snapshot`| `resolution: str = "1920x1080"` | `camera.snapshot` | Captures a high-resolution frame from the camera saved under `.ares/snapshots/`. |
| `camera_listen` | `duration_seconds: float = 3.0` | `camera.listen` | Records a 48 kHz mono PCM WAV audio sample from the beamforming microphone. |
| `camera_ptz` | `action: str = "status"`<br>`pan: int = 0`<br>`tilt: int = 0` | `camera.ptz` | Controls motorized 2-axis gimbal: `center`, `deskview`, `aim`, or `status`. |

#### Workspace & Filesystem
| Tool Name | Parameters | Required Capability | Description |
| :--- | :--- | :--- | :--- |
| `capabilities_inspect`| *None* | `capabilities.inspect` | Shows caller's identity, approved roots, and granted capability list. |
| `capability_request` | `capability: str`<br>`root: str`<br>`reason: str` | `capability.request` | Submits an audited capability elevation request for human review. |
| `workspace_list` | `path: str = "/workspace"`<br>`max_entries: int = 200` | `workspace.list` | Lists directory contents under approved roots without exposing file content. |
| `workspace_read` | `path: str`<br>`max_bytes: int = 1048576` | `workspace.read` | Reads one UTF-8 text file under an approved root (max 1 MB). |
| `workspace_write`| `path: str`<br>`content: str`<br>`expected_sha256: str = None` | `workspace.write` | Atomically writes text. Requires current SHA-256 for existing files to prevent clobbering. |
| `workspace_mkdir` | `path: str` | `workspace.mkdir` | Creates a single directory below an approved root (parents must exist). |
| `workspace_move` | `source: str`<br>`destination: str` | `workspace.move` | Atomically renames or moves a file/folder within approved roots. |

#### macOS Host Integrations (AppleScript / JXA / CLI)
| Tool Name | Parameters | Required Capability | Description |
| :--- | :--- | :--- | :--- |
| `calendar_list` | `days_ahead: int = 7` | `calendar.list` | Lists upcoming Apple Calendar events using injection-safe JXA. |
| `calendar_create` | `title: str`<br>`start_time: str`<br>`end_time: str` | `calendar.create` | Creates an Apple Calendar event after human approval. |
| `notes_list` | `folder: str = ""` | `notes.list` | Lists Apple Notes titles and modification metadata without note bodies. |
| `notes_read` | `title: str` | `notes.read` | Reads body text of one Apple Note by title. |
| `notes_create` | `title: str`<br>`body: str`<br>`folder: str = ""` | `notes.create` | Creates an Apple Note after approval. |
| `reminders_list` | `list_name: str = ""` | `reminders.list` | Lists reminders from Apple Reminders. |
| `reminders_create` | `name: str`<br>`due: str = ""` | `reminders.create` | Creates a reminder item after approval. |
| `shortcuts_list` | *None* | `shortcuts.list` | Lists installed Apple Shortcuts without running them. |
| `shortcuts_run` | `name: str`<br>`input_text: str = ""` | `shortcuts.run` | Executes a named Apple Shortcut after approval. |
| `git_status` | `path: str = "/workspace"` | `git.status` | Runs hook-disabled, read-only `git status` in an approved repository. |
| `git_diff` | `path: str = "/workspace"` | `git.diff` | Reads working-tree diff without external diff drivers or filters. |
| `service_status` | *None* | `service.status` | Probes loopback health of ARES (:8788), Jaeger (:8791), Ollama (:11434), n8n (:5678). |

---

### Server 3: `ares-webui` (18 Tools)
Session, project, and task tools exposed over stdio for agents operating through the WebUI.

| Tool Group | Tool Name | Description |
| :--- | :--- | :--- |
| **Projects** | `list_projects` | Lists session projects scoped to active profile. |
| | `create_project` | Creates project with color and description. |
| | `rename_project` | Renames project and updates color. |
| | `delete_project` | Deletes project and unassigns member sessions. |
| **Sessions** | `rename_session` | Renames active session title in sidebar. |
| | `move_session` | Assigns or unassigns session to/from a project. |
| | `list_sessions` | Lists sessions filtered by project or unassigned status. |
| **Tasks & Context**| `ares_get_runtime_context` | Reads active backend, embodiment, capabilities, and open tasks. |
| | `ares_create_task` | Creates a persistent task in the canonical task store. |
| | `ares_update_task` | Updates task status (`open`, `in_progress`, `blocked`, `done`). |
| **Research** | `ares_start_research` | Launches a background deep-research job. |
| | `ares_get_research` | Retrieves research status, citations, and syntheses. |
| **Document/Media** | `ares_extract_pdf` | Extracts text and form-field names from a PDF. |
| | `ares_fill_pdf_form` | Fills form fields in PDF and produces artifact. |
| | `ares_ingest_youtube` | Fetches transcript and metadata from YouTube URL. |
| | `ares_edit_image` | Performs operations (crop, resize, filter) on image. |
| | `ares_create_visual_report` | Generates self-contained HTML visual report artifact. |
| | `ares_list_artifacts` | Lists all generated artifacts in session workspace. |

---

### Server 4: `ares-native-mcp` (12 Tools)
Native macOS Swift tool server utilizing Apple Frameworks:

- `calendar`: EventKit integration.
- `contacts`: Contacts framework access.
- `file_operations`: Native filesystem sandboxed access.
- `image_generation`: CoreImage / ML generation.
- `math_operations`: Precision math engine.
- `memory_operations`: Long-term semantic/episodic memory.
- `notes`: Apple Notes ScriptingBridge interface.
- `screen_read`: ScreenCaptureKit display capture.
- `spotlight`: CoreSpotlight metadata query engine.
- `todo_operations`: EventKit Reminders integration.
- `user_collaboration`: Native notification center alerts.
- `weather`: WeatherKit forecast and conditions.

---

## 4. Capability Security Matrix

Grants are maintained in `~/.ares/capabilities/grants.json`. A caller identity (e.g. `hermes`, `jaeger`, `admin`) can only execute tools whose capability string is present in its granted list.

| Capability String | Admin | Hermes | Jaeger | Security Invariant |
| :--- | :---: | :---: | :---: | :--- |
| `capabilities.inspect` | Granted | Granted | Granted | Read-only identity probe |
| `capability.request` | Granted | Granted | Granted | Creates audited approval ticket |
| `workspace.list` | Granted | Granted | Granted | No file content read |
| `workspace.read` | Granted | Granted | Granted | Max 1 MB, within approved root |
| `workspace.write` | Granted | Granted | Granted | Atomic write, requires SHA-256 overwrite match |
| `workspace.mkdir` | Granted | Granted | Granted | Parent must exist |
| `workspace.move` | Granted | Granted | Granted | Both paths confined to root |
| `git.status` / `git.diff`| Granted | Granted | Granted | Hook-disabled, read-only |
| `service.status` | Granted | Granted | Granted | Loopback health read only |
| `calendar.*` / `notes.*` | Granted | Granted | Granted | Mutations require approval ticket |
| `reminders.*` / `shortcuts.*` | Granted | Granted | Granted | Executions require approval ticket |
| `camera.status` | Granted | Granted | Granted | Hardware presence & PTZ position read |
| `camera.snapshot` | Granted | Granted | Granted | Image saved only in approved `.ares/snapshots/` |
| `camera.listen` | Granted | Granted | Granted | Audio saved only in approved `.ares/audio/` |
| `camera.ptz` | Granted | Granted | Granted | Bounded angles (-180° to +180° pan, -90° to +90° tilt) |

---

## 5. Client Configuration & Discovery

To configure all installed LLM tools and IDEs idempotently:
```bash
python3 scripts/configure-mcp-clients.py
```
This automatically updates:
* **Claude Code**: Configures `ares-system` via `claude mcp add`.
* **OpenAI Codex CLI**: Configures `ares-system` in `~/.codex/config.json`.
* **Gemini CLI**: Configures `ares-system` in `~/.gemini/config/mcp_config.json`.
* **VS Code**: Configures `ares-system` in `~/Library/Application Support/Code/User/mcp.json`.
* **Claude Desktop**: Configures `~/Library/Application Support/Claude/claude_desktop_config.json`.

To verify client health and generate evidence:
```bash
python3 scripts/probe-mcp-clients.py
```
Output is saved to `~/.ares/integrations/status.json` and queryable via `GET /api/integrations`.

---

## 6. HTTP API Endpoints

The ARES controller exposes live MCP catalog and management endpoints on `http://127.0.0.1:8788`:

* **`GET /api/mcp/catalog`**:
  Returns the complete inventory of all 5 MCP servers, their network/stdio bindings, tools, schemas, and gateway settings.
* **`GET /api/mcp/tools`**:
  Returns active tool schemas registered in the runtime for the active profile.
* **`GET /api/mcp/servers`**:
  Lists configured MCP servers and their real-time connection status.
* **`POST /api/mcp/reload`**:
  Re-spawns runtime MCP server processes to pick up newly added tools and configuration changes.
