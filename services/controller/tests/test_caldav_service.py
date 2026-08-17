from __future__ import annotations

import importlib
import json

import pytest


MULTISTATUS = b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:response><d:href>/cal/test.ics</d:href><d:propstat><d:prop>
    <d:getetag>"v1"</d:getetag><c:calendar-data>BEGIN:VCALENDAR
BEGIN:VEVENT
UID:test@ares
DTSTART:20260818T170000Z
DTEND:20260818T180000Z
SUMMARY:Planning
END:VEVENT
END:VCALENDAR</c:calendar-data>
  </d:prop></d:propstat></d:response>
</d:multistatus>"""


@pytest.fixture
def service(tmp_path, monkeypatch):
    from api import caldav_service, config

    caldav_service = importlib.reload(caldav_service)
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    values = {}
    monkeypatch.setattr(
        caldav_service,
        "set_secret",
        lambda profile, key, value: values.__setitem__((profile, key), value),
    )
    monkeypatch.setattr(
        caldav_service, "get_secret", lambda profile, key: values[(profile, key)]
    )
    return caldav_service, values


def test_configuration_keeps_password_out_of_json_and_rejects_insecure_remote_http(
    service,
):
    caldav, values = service
    config = caldav.configure(
        "work",
        calendar_url="https://calendar.example.test/cal",
        username="ares",
        password="secret",
    )

    assert config["configured"] is True
    assert values[("work", caldav.SECRET_KEY)] == "secret"
    persisted = json.loads(caldav._state_file("work", "config").read_text())
    assert "password" not in persisted
    assert persisted["secret_ref"] == caldav.SECRET_KEY
    assert caldav._state_file("work", "config").stat().st_mode & 0o777 == 0o600
    with pytest.raises(caldav.CalDavError, match="requires HTTPS"):
        caldav.configure(
            "work",
            calendar_url="http://calendar.example.test/cal",
            username="ares",
            password="secret",
        )


def test_sync_persists_bounded_projection_and_survives_reload(service):
    caldav, _ = service
    caldav.configure(
        "work",
        calendar_url="https://calendar.example.test/cal",
        username="ares",
        password="secret",
    )
    calls = []

    def transport(*args, **kwargs):
        calls.append((args, kwargs))
        return 207, {}, MULTISTATUS

    result = caldav.sync("work", transport=transport)
    assert result["events"][0]["uid"] == "test@ares"
    assert calls[0][0][0] == "REPORT"
    assert caldav.list_cached_events("work")["events"][0]["summary"] == "Planning"


def test_event_put_uses_preconditions_and_safe_uid(service):
    caldav, _ = service
    caldav.configure(
        "work",
        calendar_url="https://calendar.example.test/cal",
        username="ares",
        password="secret",
    )
    calls = []

    def transport(*args, **kwargs):
        calls.append((args, kwargs))
        return 201, {"ETag": '"v2"'}, b""

    result = caldav.put_event(
        "work",
        uid="planning@ares",
        summary="Planning",
        start="20260818T170000Z",
        end="20260818T180000Z",
        transport=transport,
    )
    assert result["saved"] is True
    assert calls[0][1]["headers"]["If-None-Match"] == "*"
    assert b"SUMMARY:Planning" in calls[0][1]["body"]
    with pytest.raises(caldav.CalDavError, match="uid"):
        caldav.delete_event("work", uid="../secret", transport=transport)
