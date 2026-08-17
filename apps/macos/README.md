# ARES for macOS

The macOS target is the native ARES shell and host for permission-gated macOS
tools. It launches the local controller and presents the browser UI.

```bash
swift run ARES
swift test
```

The app may locate a JaegerAI installation but must not traverse its internal
state. Runtime data and mutations go through the controller and Jaeger bridge.
