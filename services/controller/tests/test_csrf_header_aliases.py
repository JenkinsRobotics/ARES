"""Restored Hermes WebUI CSRF header is accepted by ARES."""

from api.auth import csrf_token_from_headers


class _Headers(dict):
    def get(self, key, default=None):
        for name, value in self.items():
            if name.lower() == str(key).lower():
                return value
        return default


def test_prefers_ares_header():
    headers = _Headers({
        "X-Ares-CSRF-Token": "ares-token",
        "X-Hermes-CSRF-Token": "hermes-token",
    })
    assert csrf_token_from_headers(headers) == "ares-token"


def test_accepts_hermes_header():
    headers = _Headers({"X-Hermes-CSRF-Token": "hermes-token"})
    assert csrf_token_from_headers(headers) == "hermes-token"


def test_accepts_generic_csrf_header():
    headers = _Headers({"X-CSRF-Token": "generic"})
    assert csrf_token_from_headers(headers) == "generic"
