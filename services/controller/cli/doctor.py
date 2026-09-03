#!/usr/bin/env python3
"""ARES doctor — system + peer-runtime health checks.

Companion (JaegerAI) is a required peer product, not an in-process library.
This tool probes ARES itself and delegates readiness to Jaeger's own
``jaeger doctor`` when available.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def print_header(title: str) -> None:
    print(f"\n{Colors.BOLD}{Colors.YELLOW}=== {title} ==={Colors.RESET}")


def check_pass(msg: str) -> None:
    print(f"{Colors.GREEN}✔{Colors.RESET} {msg}")


def check_fail(msg: str, fix: str | None = None) -> None:
    print(f"{Colors.RED}✖{Colors.RESET} {msg}")
    if fix:
        print(f"  {Colors.YELLOW}↳ Fix: {fix}{Colors.RESET}")


def check_warn(msg: str, fix: str | None = None) -> None:
    print(f"{Colors.YELLOW}⚠{Colors.RESET} {msg}")
    if fix:
        print(f"  {Colors.YELLOW}↳ Suggestion: {fix}{Colors.RESET}")


def _http_ok(url: str, timeout: float = 2.0) -> tuple[bool, int | None]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ARES-Doctor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return True, response.status
    except Exception:
        return False, None


def resolve_jaeger_home() -> Path:
    raw = (
        os.environ.get("ARES_JAEGER_HOME")
        or os.environ.get("JAEGER_HOME")
        or str(Path.home() / "jaeger")
    )
    return Path(os.path.expandvars(raw)).expanduser().resolve()


def find_webui_python(ares_home: Path, ares_src: Path | None) -> Path | None:
    candidates = [
        ares_home / "webui" / "venv" / "bin" / "python",
        ares_home / "webui" / ".venv" / "bin" / "python",
    ]
    if ares_src is not None:
        candidates.extend(
            [
                ares_src / "webui" / "venv" / "bin" / "python",
                ares_src / "webui" / ".venv" / "bin" / "python",
            ]
        )
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def probe_jaeger(jaeger_home: Path) -> None:
    print_header("Companion Runtime (JaegerAI peer)")

    launcher = jaeger_home / "jaeger"
    venv_py = jaeger_home / ".venv" / "bin" / "python"

    if launcher.is_file() and os.access(launcher, os.X_OK):
        check_pass(f"JaegerAI launcher found: {launcher}")
    else:
        check_fail(
            f"JaegerAI launcher missing at {launcher}",
            "Install peer: curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JaegerAI/master/scripts/install.sh | bash",
        )
        return

    if venv_py.is_file():
        check_pass(f"JaegerAI venv present: {venv_py}")
    else:
        check_warn(
            "JaegerAI .venv not found",
            f"cd {jaeger_home} && ./install.sh",
        )

    try:
        from api.providers.jaeger.streaming import query_local_companion

        identity = query_local_companion("identity", {})
        name = str(identity.get("agent_name") or identity.get("instance") or "").strip()
        if name:
            check_pass(f"Companion instance: {name}")
        else:
            check_warn("No Companion instance reported", "Complete ARES onboarding or run: jaeger agent create")
    except Exception as exc:
        check_warn("Could not query the Companion instance", str(exc))

    # Prefer Jaeger's own doctor when available (machine-readable when possible).
    try:
        result = subprocess.run(
            [str(launcher), "doctor", "--doctor-check"],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(jaeger_home),
        )
        if result.returncode == 0:
            check_pass("jaeger doctor --doctor-check: OK")
        else:
            tail = (result.stdout or result.stderr or "").strip().splitlines()
            detail = tail[-1] if tail else f"exit {result.returncode}"
            check_warn(
                f"jaeger doctor reported issues ({detail})",
                f"Run: {launcher} doctor",
            )
    except FileNotFoundError:
        check_warn("Could not execute jaeger doctor", "Ensure the launcher is executable")
    except subprocess.TimeoutExpired:
        check_warn("jaeger doctor timed out", "Run manually: jaeger doctor")
    except Exception as exc:
        check_warn(f"jaeger doctor failed: {exc}")

    # ARES wires Jaeger at its product endpoint, not an in-process import.
    jaeger_url = os.environ.get("ARES_JAEGER_WEBUI_URL", "http://127.0.0.1:8790").rstrip("/")
    ok, status = _http_ok(jaeger_url, timeout=1.5)
    if ok:
        check_pass(f"Jaeger endpoint healthy at {jaeger_url} (HTTP {status})")
    else:
        check_warn(
            f"Jaeger is not responding at {jaeger_url}",
            "Start the JaegerAI peer product (ARES integrates via this endpoint only).",
        )


# The canonical ARES controller port. ctl.sh, start.sh, install.sh,
# http_security, streaming, native_system and the `ares` launcher all use
# 8788, and the launcher exports ARES_WEBUI_PORT. doctor alone hardcoded
# 8787, so it reported "WebUI server is not responding" against a healthy
# server and printed a Tailscale URL nobody could reach.
DEFAULT_WEBUI_PORT = 8788


def webui_port() -> int:
    """The port the controller is actually expected on.

    Honours ARES_WEBUI_PORT (what `ares` exports) and falls back to the
    canonical default. A malformed value falls back rather than raising —
    doctor's job is to report health, not to die parsing its own config.
    """
    raw = os.environ.get("ARES_WEBUI_PORT", "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_WEBUI_PORT


# FastAPI mounts this tree (see fastapi_app.frontend.DEFAULT_FRONTEND_ROOT).
PRODUCTION_UI_RELATIVE = Path("services") / "controller" / "apps" / "dashboard" / "static"
PRODUCTION_UI_LABEL = "services/controller/apps/dashboard/static"

# External products ARES reaches by loopback URL/port only — never by editing
# those repos. Defaults match services/controller/core/runtimes.py.
PEER_PRODUCT_ENDPOINTS = (
    ("Hermes", "ARES_HERMES_WEBUI_URL", "http://127.0.0.1:8787"),
    ("Jaeger", "ARES_JAEGER_WEBUI_URL", "http://127.0.0.1:8790"),
    ("OpenClaw", "ARES_OPENCLAW_WEBUI_URL", "http://127.0.0.1:18789"),
)


def _xcode_clt_present() -> bool:
    """True when Xcode or Command Line Tools are actually usable on Darwin."""
    binary = shutil.which("xcode-select")
    if not binary:
        return False
    try:
        completed = subprocess.run(
            [binary, "-p"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    developer_dir = (completed.stdout or "").strip()
    return bool(developer_dir) and Path(developer_dir).is_dir()


def host_dependencies_report() -> list[tuple[str, str, str | None]]:
    """Required host tools. Missing Ollama or (on Darwin) Xcode/CLT is a fail.

    Tests mock ``shutil.which`` / ``_xcode_clt_present`` so this is deterministic
    even on a machine that already has the tools.
    """
    findings: list[tuple[str, str, str | None]] = []
    ollama = shutil.which("ollama")
    if ollama:
        findings.append(("pass", f"Ollama found: {ollama}", None))
    else:
        findings.append((
            "fail",
            "Ollama is missing.",
            "Install Ollama from https://ollama.com and ensure `ollama` is on PATH.",
        ))
    if platform.system() == "Darwin":
        if _xcode_clt_present():
            findings.append(("pass", "Xcode Command Line Tools are present.", None))
        else:
            findings.append((
                "fail",
                "Xcode Command Line Tools are missing.",
                "Install them with: xcode-select --install",
            ))
    return findings


def peer_product_endpoints() -> list[tuple[str, str]]:
    """Hermes / Jaeger / OpenClaw URLs ARES is wired to on this host."""
    endpoints: list[tuple[str, str]] = []
    for name, env_key, default in PEER_PRODUCT_ENDPOINTS:
        raw = os.environ.get(env_key, default).strip() or default
        endpoints.append((name, raw.rstrip("/")))
    return endpoints


def peer_endpoints_report() -> list[tuple[str, str, str | None]]:
    """Probe peer products at their ARES-wired loopback URLs.

    Down peers are warnings, not hard failures: they are external products.
    The wiring itself (which URL/port ARES uses) is what doctor must name.
    """
    findings: list[tuple[str, str, str | None]] = []
    for name, url in peer_product_endpoints():
        ok, status = _http_ok(url, timeout=1.5)
        if ok:
            findings.append(
                ("pass", f"{name} endpoint healthy at {url} (HTTP {status})", None)
            )
        else:
            findings.append((
                "warn",
                f"{name} is not responding at {url}",
                f"Start the {name} peer product. ARES integrates via this endpoint only.",
            ))
    return findings


def diagnose_host_dependencies() -> int:
    """Render required-tool findings. Return 1 if any failed, else 0."""
    failed = 0
    for status, msg, fix in host_dependencies_report():
        if status == "pass":
            check_pass(msg)
        elif status == "warn":
            check_warn(msg, fix)
        else:
            check_fail(msg, fix)
            failed = 1
    return failed


def frontend_ownership_report(
    repo_root: Path,
) -> list[tuple[str, str, str | None]]:
    """Which frontend actually ships, stated out loud.

    FastAPI mounts ``services/controller/apps/dashboard/static`` — the value of
    ``fastapi_app.frontend.DEFAULT_FRONTEND_ROOT``. ``apps/web/static`` and
    ``apps/web/dist`` are not production. ``apps/web-react`` may still exist
    as a CI-tested tree that no Python under services/ serves.

    Ownership is reported, never guessed at: web-react is called out as
    present-but-not-served rather than promoted on a heuristic.

    Returns ``(status, message, fix)`` triples — ``pass`` | ``warn`` |
    ``fail`` — so the caller owns rendering and tests can read the result.
    """
    findings: list[tuple[str, str, str | None]] = []

    production = repo_root / PRODUCTION_UI_RELATIVE
    if (production / "index.html").is_file():
        findings.append(
            ("pass", f"Production UI: {PRODUCTION_UI_LABEL} ({production})", None))
    elif production.is_dir():
        findings.append((
            "fail",
            f"Production UI {PRODUCTION_UI_LABEL} exists but has no index.html "
            f"({production}) — the server will 404 on /.",
            f"Restore {PRODUCTION_UI_LABEL}/index.html from git.",
        ))
    else:
        findings.append((
            "fail",
            f"Production UI {PRODUCTION_UI_LABEL} is missing ({production}).",
            "Check out the full repo; the FastAPI app mounts this path.",
        ))

    react = repo_root / "apps" / "web-react"
    if react.is_dir():
        built = (react / "dist" / "index.html").is_file()
        detail = "built (dist/ present)" if built else "not built"
        findings.append((
            "warn",
            f"apps/web-react is present and {detail}, but is NOT served — "
            "no code under services/ references it. CI typechecks and "
            "tests it, so a green pipeline does not mean it ships.",
            f"Edit {PRODUCTION_UI_LABEL} to change the running UI. To promote "
            "web-react deliberately, pass frontend_root=apps/web-react/dist "
            "to fastapi_app.main and update this check.",
        ))

    return findings


def run_diagnostics() -> int:
    print(f"{Colors.BOLD}ARES Diagnostic Tool (Doctor){Colors.RESET}")
    print("Checking system health and peer runtimes...\n")
    failures = 0

    print_header("System & Environment")
    py_ver = sys.version_info
    if py_ver.major >= 3 and py_ver.minor >= 10:
        check_pass(f"Python version {py_ver.major}.{py_ver.minor} is supported.")
    else:
        check_fail(
            f"Python version {py_ver.major}.{py_ver.minor} is unsupported.",
            "Upgrade to Python 3.10+",
        )
        failures += 1

    os_name = platform.system()
    check_pass(f"Operating System: {os_name} {platform.release()}")

    print_header("Host Dependencies")
    failures += diagnose_host_dependencies()

    print_header("Frontend Ownership")
    try:
        from fastapi_app import frontend as _frontend

        _repo_root = Path(_frontend.__file__).resolve().parents[3]
    except Exception:
        # doctor may run from an installed copy without the app importable;
        # fall back to walking up from this file.
        _repo_root = Path(__file__).resolve().parents[3]
    for _status, _msg, _fix in frontend_ownership_report(_repo_root):
        if _status == "pass":
            check_pass(_msg)
        elif _status == "warn":
            check_warn(_msg, _fix)
        else:
            check_fail(_msg, _fix)
            failures += 1

    print_header("ARES Core Components")
    ares_home = Path(os.path.expanduser("~/.ares")).resolve()
    install_json = ares_home / "installation.json"
    # settings may live under install home or symlink target webui/
    settings_candidates = [
        ares_home / "webui" / "settings.json",
        ares_home / "settings.json",
    ]

    if install_json.exists():
        check_pass(f"ARES installation manifest found ({install_json})")
        try:
            manifest = json.loads(install_json.read_text(encoding="utf-8"))
            src = manifest.get("source_dir")
            if src:
                check_pass(f"Source dir: {src}")
        except Exception:
            check_warn("installation.json present but not valid JSON")
    else:
        check_fail(
            "ARES installation manifest missing.",
            "Run bash install.sh from the ARES checkout",
        )
        failures += 1

    ares_src = None
    if install_json.exists():
        try:
            ares_src = Path(json.loads(install_json.read_text()).get("source_dir", ""))
            if not ares_src.exists():
                ares_src = None
        except Exception:
            ares_src = None

    webui_py = find_webui_python(ares_home, ares_src)
    if webui_py:
        check_pass(f"WebUI Python: {webui_py}")
    else:
        check_fail(
            "WebUI virtualenv python not found",
            "Re-run: bash install.sh --role primary",
        )
        failures += 1

    _port = webui_port()
    ok, status = _http_ok(f"http://127.0.0.1:{_port}/health")
    if not ok:
        ok, status = _http_ok(f"http://127.0.0.1:{_port}/api/onboarding/status")
    if ok:
        check_pass(f"ARES WebUI responding on port {_port} (HTTP {status})")
    else:
        check_fail(
            f"ARES WebUI server is not responding on {_port}.",
            "Start with: ares start   or open ARES.app",
        )
        failures += 1

    print_header("Remote Access & Networking")
    if shutil.which("tailscale"):
        try:
            out = subprocess.check_output(
                ["tailscale", "ip", "-4"],
                stderr=subprocess.STDOUT,
                timeout=2,
            ).decode()
            lines = [
                line.strip()
                for line in out.splitlines()
                if line.strip() and not line.startswith("Warning:")
            ]
            if lines:
                check_pass("Tailscale connected. Remote URL: "
                           f"http://{lines[-1]}:{webui_port()}")
            else:
                check_warn(
                    "Tailscale installed but no IP",
                    "Run `tailscale up` to enable remote access.",
                )
        except Exception:
            check_warn(
                "Could not query Tailscale",
                "Run `tailscale up` if you want remote access.",
            )
    else:
        check_warn(
            "Tailscale not found (optional).",
            "Install from https://tailscale.com/download for phone/remote access.",
        )

    print_header("Framework Orchestration")
    configured_backend = "unconfigured"
    for settings_json in settings_candidates:
        if settings_json.exists():
            try:
                settings = json.loads(settings_json.read_text(encoding="utf-8"))
                configured_backend = settings.get("ares_backend", "unconfigured")
                check_pass(f"settings.json: {settings_json} (backend={configured_backend})")
                break
            except Exception:
                check_warn(f"Could not parse {settings_json}")
    else:
        check_warn("No WebUI settings.json found yet (fresh install is OK)")

    if configured_backend == "unconfigured":
        check_warn(
            "No backend framework configured yet.",
            "Complete ARES onboarding (Companion = JaegerAI).",
        )
    elif configured_backend in ("jaeger", "jaeger_local", "hybrid"):
        check_pass(f"Backend configured: {configured_backend}")
    else:
        check_warn(f"Unknown backend configured: {configured_backend}")

    print_header("Peer Product Endpoints")
    for _status, _msg, _fix in peer_endpoints_report():
        if _status == "pass":
            check_pass(_msg)
        elif _status == "warn":
            check_warn(_msg, _fix)
        else:
            check_fail(_msg, _fix)
            failures += 1

    probe_jaeger(resolve_jaeger_home())

    print("\n" + "-" * 50)
    print(
        "Diagnostics complete. Fix ✖ items first, then re-run `ares doctor`. "
        "Companion setup issues usually need `jaeger doctor` or ARES onboarding."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_diagnostics())
