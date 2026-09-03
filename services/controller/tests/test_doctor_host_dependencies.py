"""Missing Ollama / Xcode must fail doctor and setup with a named message.

Mocks keep this deterministic on a machine that already has the tools.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import cli.doctor as doctor


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "scripts" / "require-host-dependencies.sh"
LAUNCHER = ROOT / "bin" / "ares"


def _which_without_ollama(name: str, path: str | None = None):
    if name == "ollama":
        return None
    return "/usr/bin/" + name


def test_missing_ollama_is_a_named_failure(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", _which_without_ollama)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Linux")
    findings = doctor.host_dependencies_report()
    fails = [(s, m, f) for s, m, f in findings if s == "fail"]
    assert fails, findings
    assert any("Ollama is missing" in m for _, m, _ in fails)
    assert doctor.diagnose_host_dependencies() == 1


def test_missing_xcode_on_darwin_is_a_named_failure(monkeypatch, capsys):
    monkeypatch.setattr(doctor.shutil, "which", lambda name, path=None: "/opt/homebrew/bin/ollama" if name == "ollama" else "/usr/bin/" + name)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(doctor, "_xcode_clt_present", lambda: False)
    findings = doctor.host_dependencies_report()
    fails = [m for s, m, _ in findings if s == "fail"]
    assert any("Xcode Command Line Tools are missing" in m for m in fails), findings
    assert doctor.diagnose_host_dependencies() == 1
    out = capsys.readouterr().out
    assert "Xcode Command Line Tools are missing" in out


def test_xcode_is_not_required_off_darwin(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name, path=None: "/usr/bin/ollama" if name == "ollama" else "/usr/bin/" + name)
    monkeypatch.setattr(doctor.platform, "system", lambda: "Linux")
    monkeypatch.setattr(doctor, "_xcode_clt_present", lambda: False)
    findings = doctor.host_dependencies_report()
    assert all(s == "pass" for s, _, _ in findings), findings
    assert not any("Xcode" in m for _, m, _ in findings)
    assert doctor.diagnose_host_dependencies() == 0


def test_xcode_clt_present_uses_xcode_select_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor.shutil, "which", lambda name, path=None: None)
    assert doctor._xcode_clt_present() is False

    fake = tmp_path / "xcode-select"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setattr(doctor.shutil, "which", lambda name, path=None: str(fake) if name == "xcode-select" else None)

    def boom(*_a, **_k):
        return subprocess.CompletedProcess([str(fake), "-p"], 1, "", "xcode-select: error")

    monkeypatch.setattr(doctor.subprocess, "run", boom)
    assert doctor._xcode_clt_present() is False


def test_peer_endpoints_name_hermes_jaeger_openclaw_ports(monkeypatch):
    monkeypatch.delenv("ARES_HERMES_WEBUI_URL", raising=False)
    monkeypatch.delenv("ARES_JAEGER_WEBUI_URL", raising=False)
    monkeypatch.delenv("ARES_OPENCLAW_WEBUI_URL", raising=False)
    endpoints = dict(doctor.peer_product_endpoints())
    assert endpoints["Hermes"] == "http://127.0.0.1:8787"
    assert endpoints["Jaeger"] == "http://127.0.0.1:8790"
    assert endpoints["OpenClaw"] == "http://127.0.0.1:18789"
    monkeypatch.setattr(doctor, "_http_ok", lambda url, timeout=1.5: (False, None))
    report = doctor.peer_endpoints_report()
    text = " ".join(m for _, m, _ in report)
    assert "8787" in text and "8790" in text and "18789" in text
    assert all(s == "warn" for s, _, _ in report)


def _fake_path(tmp_path: Path, *, ollama: bool, darwin: bool, xcode: bool) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uname = "Darwin" if darwin else "Linux"
    (bin_dir / "uname").write_text("#!/bin/sh\necho %s\n" % uname)
    (bin_dir / "uname").chmod(0o755)
    if ollama:
        (bin_dir / "ollama").write_text("#!/bin/sh\nexit 0\n")
        (bin_dir / "ollama").chmod(0o755)
    if darwin:
        body = "#!/bin/sh\n%s\n" % ("echo /Applications/Xcode.app/Contents/Developer; exit 0" if xcode else "exit 1")
        (bin_dir / "xcode-select").write_text(body)
        (bin_dir / "xcode-select").chmod(0o755)
    return bin_dir


def _run_helper(bin_dir: Path) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"]),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    return subprocess.run(
        ["bash", str(HELPER)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_bash_helper_fails_when_ollama_missing(tmp_path):
    proc = _run_helper(_fake_path(tmp_path, ollama=False, darwin=False, xcode=False))
    assert proc.returncode != 0
    assert "Ollama is missing" in (proc.stderr + proc.stdout)


def test_bash_helper_fails_when_xcode_missing_on_darwin(tmp_path):
    proc = _run_helper(_fake_path(tmp_path, ollama=True, darwin=True, xcode=False))
    assert proc.returncode != 0
    assert "Xcode Command Line Tools are missing" in (proc.stderr + proc.stdout)


def test_bash_helper_passes_when_tools_present(tmp_path):
    proc = _run_helper(_fake_path(tmp_path, ollama=True, darwin=True, xcode=True))
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_ares_launcher_host_deps_check_fails_without_ollama(tmp_path):
    fake = _fake_path(tmp_path, ollama=False, darwin=False, xcode=False)
    env = {
        "PATH": os.pathsep.join([str(fake), "/usr/bin", "/bin"]),
        "HOME": os.environ.get("HOME", "/tmp"),
        "ARES_HOST_DEPS_CHECK": "1",
    }
    proc = subprocess.run(
        ["bash", str(LAUNCHER)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode != 0
    assert "Ollama is missing" in (proc.stderr + proc.stdout)


def test_install_system_services_fails_when_ollama_missing(monkeypatch):
    import importlib.util

    script = ROOT / "scripts" / "install-system-services.py"
    spec = importlib.util.spec_from_file_location("install_system_services", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="Ollama is missing"):
        module.require_ollama()
