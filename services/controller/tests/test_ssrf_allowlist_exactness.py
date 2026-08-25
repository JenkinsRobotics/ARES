"""The SSRF local-host allowlist must match hostnames, not substrings.

api/config.py guards custom-provider fetches by resolving the hostname and
refusing private/loopback/link-local addresses, with an exemption for
known-local runtimes (ollama, localhost, lmstudio, ...).

That exemption was a SUBSTRING test — ``any(k in host_l for k in ...)`` —
so any domain an attacker can register whose name merely CONTAINS one of
those tokens inherited the exemption. ``ollama.attacker.com`` resolving to
169.254.169.254 sailed straight through the guard.

The existing issue-1105 tests could not catch this: they assert that
strings like ``'SSRF: resolved hostname to private IP'`` appear in the
source. They do appear. The guard was bypassable anyway, which is what a
source-grep test can never tell you. These tests exercise the predicate.

The legitimate escape hatch already exists and is unaffected: hostnames
from the operator's own custom_providers are added to _ssrf_trusted_hosts
by exact match, so a real ollama.mylan.internal stays reachable.
"""

from __future__ import annotations

import pytest

from api.config import _ssrf_host_is_known_local as known_local


@pytest.mark.parametrize("host", [
    "ollama",
    "localhost",
    "127.0.0.1",
    "lmstudio",
    "lm-studio",
])
def test_bare_local_names_still_allowed(host):
    """The whole point of the exemption must keep working."""
    assert known_local(host, frozenset()) is True


@pytest.mark.parametrize("host", [
    "ollama.local",
    "lmstudio.local",
])
def test_mdns_local_names_allowed(host):
    """.local is the mDNS namespace a LAN runtime actually advertises on."""
    assert known_local(host, frozenset()) is True


@pytest.mark.parametrize("host", [
    "ollama.attacker.com",
    "my-localhost.evil.net",
    "lmstudio.evil.io",
    "not-127.0.0.1.evil.com",
    "localhost.attacker.co.uk",
    "evil-ollama-proxy.com",
])
def test_attacker_registrable_domains_are_not_exempt(host):
    """A registrable domain that merely CONTAINS a local token is not local."""
    assert known_local(host, frozenset()) is False, (
        f"{host} bypassed the SSRF guard via substring matching")


def test_operator_configured_hosts_are_still_trusted():
    """The real escape hatch: exact hostnames from custom_providers."""
    assert known_local("ollama.mylan.internal",
                       frozenset({"ollama.mylan.internal"})) is True


def test_trusted_set_is_matched_exactly_not_by_substring():
    """Trust must not leak to neighbours of a trusted name."""
    trusted = frozenset({"gpu.mylan.internal"})
    assert known_local("gpu.mylan.internal.evil.com", trusted) is False


def test_case_is_normalised():
    assert known_local("LocalHost", frozenset()) is True
    assert known_local("OLLAMA.MyLan.Internal",
                       frozenset({"ollama.mylan.internal"})) is True
