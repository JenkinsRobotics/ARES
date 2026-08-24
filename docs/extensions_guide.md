# ARES Extension Developer Guide

This document specifies the standard architecture for building, packaging, and installing extensions for **ARES** and the **JaegerAI** agent runtime.

The canonical reference implementation is **`ares-minecraft`** ([manifest.json](file:///Users/matthewjenkins/GitHub/ares-minecraft/manifest.json)).

---

## 1. Overview & Capabilities

An ARES extension is an autonomous, self-contained subsystem that can provide:
- **`sidecar`**: A dedicated local service (Node.js, Python, Rust, Go) communicating over loopback REST/WebSocket.
- **`dashboard_tab`**: A custom frontend UI embedded directly into the ARES WebUI sidebar and layout.
- **`agent_tools`**: Native Python tool functions invokable during agent turns.
- **`mcp`**: A standard Model Context Protocol (MCP) server running via `stdio` for agent tool execution.

```
┌────────────────────────────────────────────────────────┐
│                        ARES UI                         │
│  ┌───────────────────────┐  ┌───────────────────────┐  │
│  │   Core WebUI Views    │  │ Extension Tabs (HUD)  │  │
│  └───────────┬───────────┘  └───────────┬───────────┘  │
└──────────────┼──────────────────────────┼──────────────┘
               │                          │
┌──────────────▼───────────┐  ┌───────────▼───────────┐
│     ARES Controller      │  │   Extension Sidecar   │
│  (FastAPI /api/extensions) │  │  (HTTP / WebSocket)   │
└──────────────┬───────────┘  └───────────────────────┘
               │
┌──────────────▼───────────┐
│     JaegerAI Runtime     │ ◀─── [MCP Server (stdio)]
│    (Tool Dispatches)     │
└──────────────────────────┘
```

---

## 2. Extension Manifest (`manifest.json`)

Every extension must include a `manifest.json` at its root:

```json
{
  "id": "ares-minecraft",
  "name": "ARES Minecraft Companion",
  "version": "1.0.0",
  "description": "Embodied autonomous Minecraft AI companion powered by Mineflayer, dynamic pathfinding, and ARES.",
  "author": "Jenkins Robotics",
  "homepage": "https://github.com/JenkinsRobotics/ares-minecraft",
  "license": "MIT",
  "category": "Gaming & Robotics",
  "capabilities": [
    "sidecar",
    "dashboard_tab",
    "agent_tools",
    "mcp"
  ],
  "scripts": [
    "dashboard/app.js"
  ],
  "stylesheets": [
    "dashboard/style.css"
  ],
  "sidecar": {
    "type": "loopback",
    "origin": "http://127.0.0.1:3847",
    "health_path": "/health"
  },
  "tab": {
    "id": "minecraft",
    "label": "Minecraft",
    "path": "/minecraft",
    "entry": "dashboard/index.html",
    "icon": "Gamepad2"
  },
  "tools": {
    "module": "tools.minecraft",
    "definitions": [
      "mc_status",
      "mc_move_to",
      "mc_follow_player",
      "mc_mine",
      "mc_craft",
      "mc_chat",
      "mc_attack",
      "mc_inventory"
    ]
  },
  "permissions": {
    "storage": {
      "owned": true
    }
  },
  "settings_schema": [
    {
      "key": "server_host",
      "type": "string",
      "label": "Minecraft Server Host",
      "default": "localhost",
      "description": "Hostname or IP address of the server"
    },
    {
      "key": "server_port",
      "type": "integer",
      "label": "Server Port",
      "default": 25565,
      "description": "Port for the server"
    }
  ]
}
```

---

## 3. Sidecar Lifecycle & Proxying

- **Loopback Only**: Sidecars must bind exclusively to `127.0.0.1` (never `0.0.0.0` unless explicitly authenticated).
- **Health Probing**: Sidecars must expose a `GET /health` endpoint returning `{"status": "ok"}` or `{"ok": true}`.
- **Reverse Proxy**: ARES Controller forwards requests from `http://127.0.0.1:8788/api/extensions/<id>/proxy/*` to the sidecar's declared `origin`.

---

## 4. Model Context Protocol (MCP) Integration

Extensions provide stdio MCP servers for seamless tool execution by JaegerAI:
- Stdio MCP script path: `tools/mcp_server.py` or `tools/mcp_minecraft.py`.
- Registered automatically with JaegerAI when installed or enabled in ARES Settings.

---

## 5. Installation & Discovery

Extensions can be installed by:
1. Placing the folder inside `$ARES_HOME/extensions/<extension-id>`.
2. Running the ARES CLI command:
   ```bash
   ares extension install <github-repo-or-path>
   ```
3. Activating via the ARES WebUI Settings $\rightarrow$ Extensions Gallery.
