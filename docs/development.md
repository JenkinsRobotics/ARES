# Development

## Requirements

- Python 3.11–3.13 for controller tests
- Swift 6.1 for the macOS app
- A separately installed native JaegerAI runtime for live integration tests
- Apple `container` for the isolated Hermes and optional n8n services
- A native Ollama daemon for local weights and Ollama Cloud model routing

## Run

```bash
cd services/controller
./start_ares.sh
```

The safe default is `127.0.0.1:8788`. Configure authentication before using a
non-loopback bind.

Install the pinned protocol edge and optional workflow container from the
repository root:

```bash
./scripts/install-agentgateway.py
./scripts/configure-host-capabilities.py
./scripts/configure-system-fabric.py
./scripts/install-n8n-container.sh
./scripts/install-system-services.py
```

## Test

```bash
cd services/controller
PYTHONPATH=../.. .venv/bin/python -m pytest -q \
  tests/test_automation_controller.py tests/test_system_protocols.py
cd ../..
swift test
```

Add targeted controller and end-to-end tests for the domain being changed.
JaegerAI is a separate dependency: communicate through its loopback versioned
runner API, never by importing, booting a second copy, or editing its state.
Hermes is also separate: use the installed launcher or its public WebUI API.

## Troubleshooting: AIAgent not available

Diagnose the local editable install before changing code:

```bash
readlink services/controller/.venv/bin/python
ls -la services/controller/.venv
ls -la path/to/agent/__init__.py
services/controller/.venv/bin/python -c 'import agent; print(agent.__file__)'
```

If the package is absent from the selected environment, activate that environment
from the package checkout and run `pip install -e .`. Then repeat the import
probe. Do not work around a broken environment by adding source-tree paths to
production code.
