# ARES

**Artificial Reasoning & Execution System**

One assistant. Persistent memory. Verified action.

You talk to one thing — one conversation, one memory, one place that knows you. ARES remembers everything, verifies before acting, and uses whatever model or agent is best for the task. The agents are replaceable hands. Swap any model underneath and nothing is lost.

## Quick Start

```bash
git clone https://github.com/JenkinsRobotics/ARES.git
cd ARES
bash install.sh
./start.sh
# → http://localhost:8788
```

Or run the native macOS app:
```bash
swift run ARES
```

## Documentation

- **[Vision](docs/vision.md)** — what ARES is, the problem it solves, and how it works
- **[Architecture](docs/architecture.md)** — dispatch, guard, memory, runtime, boundaries
- **[Development](docs/development.md)** — install, run, Docker, troubleshooting, contributing
- **[API Reference](docs/api.md)** — endpoints and contracts

## Repository

```
ARES/
├── apps/macos/            # Native macOS app (SwiftUI/WKWebView → :8788)
├── apps/web/              # React UI
│   └── src/
│       ├── features/chat/           # Chat page
│       ├── components/shell/        # Session list + frame
│       └── styles/chat-layout.css   # Phone/desktop chat padding
├── services/controller/   # FastAPI backend + API + tests
├── core/                  # Planner, orchestrator, trust, verification
├── integrations/          # Worker adapters (Jaeger, Hermes, Claude, Codex, Ollama)
└── docs/                  # Documentation (+ rfcs/, decisions/)
```

## Owner

Matthew Jenkins (shuwalker) · Jenkins Robotics
