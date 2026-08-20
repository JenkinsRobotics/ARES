"""Wave A persistence and protocol path across work-management owners."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import threading


class _CalendarHandler(BaseHTTPRequestHandler):
    event = b""

    def log_message(self, _format, *_args):
        return

    def do_PUT(self):  # noqa: N802 - stdlib callback name
        type(self).event = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(201)
        self.send_header("ETag", '"wave-a"')
        self.end_headers()

    def do_REPORT(self):  # noqa: N802 - stdlib callback name
        event = type(self).event.decode() or "BEGIN:VCALENDAR\nEND:VCALENDAR"
        payload = f"""<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>/calendar/wave-a.ics</d:href><d:propstat><d:prop><d:getetag>"wave-a"</d:getetag><c:calendar-data>{event}</c:calendar-data></d:prop></d:propstat></d:response></d:multistatus>""".encode()
        self.send_response(207)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def test_wave_a_create_restart_and_remote_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_HOME", str(tmp_path / "ares"))
    from api import caldav_service, config, kanban_store, schedule_jobs

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    secrets = {}
    monkeypatch.setattr(
        caldav_service,
        "set_secret",
        lambda profile, key, value: secrets.__setitem__((profile, key), value),
    )
    monkeypatch.setattr(
        caldav_service, "get_secret", lambda profile, key: secrets[(profile, key)]
    )
    kanban_store = importlib.reload(kanban_store)
    schedule_jobs = importlib.reload(schedule_jobs)

    kanban_store.create_board("delivery")
    with kanban_store.connect_closing(board="delivery") as connection:
        task_id = kanban_store.create_task(
            connection, title="Ship Wave A", idempotency_key="wave-a"
        )
    schedule = schedule_jobs.create_job(prompt="Review Wave A", schedule="0 9 * * *")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _CalendarHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        calendar_url = f"http://127.0.0.1:{server.server_port}/calendar/"
        caldav_service.configure(
            "default", calendar_url=calendar_url, username="ares", password="secret"
        )
        caldav_service.put_event(
            "default",
            uid="wave-a@ares",
            summary="Wave A review",
            start="20260818T170000Z",
            end="20260818T180000Z",
        )
        synchronized = caldav_service.sync("default")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert synchronized["events"][0]["uid"] == "wave-a@ares"

    # Reload each owner to model a controller restart and verify durable state.
    kanban_store = importlib.reload(kanban_store)
    schedule_jobs = importlib.reload(schedule_jobs)
    with kanban_store.connect_closing(board="delivery") as connection:
        assert kanban_store.get_task(connection, task_id).title == "Ship Wave A"
    assert schedule_jobs.get_job(schedule["id"])["prompt"] == "Review Wave A"
    assert (
        caldav_service.list_cached_events("default")["events"][0]["summary"]
        == "Wave A review"
    )
