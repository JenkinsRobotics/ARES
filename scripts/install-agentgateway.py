#!/usr/bin/env python3
"""Install the pinned native Agentgateway binary without root privileges."""

from __future__ import annotations

import hashlib
import os
import platform
import stat
import tempfile
import urllib.request
from pathlib import Path


VERSION = "1.5.0"
ASSET = "agentgateway-darwin-arm64"
SHA256 = "da432d35bd696da0564f7b2b6bbc783542b6b9c616d6c0c4d4c3daef9dfa11a1"
URL = f"https://github.com/agentgateway/agentgateway/releases/download/v{VERSION}/{ASSET}"


def main() -> int:
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "aarch64"}:
        raise SystemExit("This installer currently supports Apple Silicon macOS only.")
    install_dir = Path.home() / "Library" / "Application Support" / "ARES" / "bin"
    destination = install_dir / f"agentgateway-v{VERSION}"
    link = Path.home() / ".local" / "bin" / "agentgateway"
    install_dir.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == SHA256:
        print(f"Agentgateway {VERSION} is already verified at {destination}")
    else:
        with tempfile.NamedTemporaryFile(prefix="ares-agentgateway-", delete=False) as handle:
            temporary = Path(handle.name)
            with urllib.request.urlopen(URL, timeout=120) as response:
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        if digest != SHA256:
            temporary.unlink(missing_ok=True)
            raise SystemExit(f"Agentgateway checksum mismatch: expected {SHA256}, got {digest}")
        temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(temporary, destination)
        print(f"Installed Agentgateway {VERSION} at {destination}")

    if link.is_symlink() or not link.exists():
        link.unlink(missing_ok=True)
        link.symlink_to(destination)
    elif link.resolve() != destination:
        raise SystemExit(f"Refusing to replace non-symlink command at {link}")
    print(f"Command link: {link}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
