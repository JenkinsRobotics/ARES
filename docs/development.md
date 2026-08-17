# Development

## Requirements

- Python 3.11–3.13 for controller tests
- Swift 6.1 for the macOS app
- A separately installed JaegerAI runtime for live integration tests

## Run

```bash
cd services/controller
./start_ares.sh
```

The safe default is `127.0.0.1:8788`. Configure authentication before using a
non-loopback bind.

## Test

```bash
cd services/controller
./scripts/test.sh -q tests/test_jaeger_ownership_literals.py
cd ../..
swift test
```

Add targeted controller and end-to-end tests for the domain being changed.
JaegerAI is a separate dependency: resolve it through the shared path resolver
and communicate through its bridge, never by importing or editing its state.

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
