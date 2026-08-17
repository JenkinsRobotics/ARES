"""Wave C/D content features share one workspace-safe artifact store."""

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


def _workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "api.file_operations._workspace",
        lambda _session_id: (tmp_path, SimpleNamespace(profile="default")),
    )


def test_artifact_inventory_is_calculated_from_workspace(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from api.workspace_artifacts import list_artifacts, read_workspace_bytes, write_artifact

    artifact = write_artifact("session-1", "Report name.html", b"<h1>Report</h1>")
    assert artifact["path"] == "artifacts/Report-name.html"
    assert read_workspace_bytes("session-1", artifact["path"]) == b"<h1>Report</h1>"
    inventory = list_artifacts("session-1")
    assert inventory["count"] == 1
    assert inventory["items"][0]["name"] == "Report-name.html"


def test_visual_report_escapes_user_content(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from api.generated_artifacts import create_visual_report

    result = create_visual_report(
        "session-1",
        title="Status <script>",
        summary="Safe & clear",
        sections=[{"heading": "Result", "body": "<img src=x onerror=alert(1)>"}],
    )
    content = (tmp_path / result["artifact"]["path"]).read_text()
    assert "<script>" not in content
    assert "&lt;script&gt;" in content
    assert "&lt;img" in content


def test_image_edit_writes_gallery_artifact(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from PIL import Image
    from api.generated_artifacts import edit_image, gallery

    source = tmp_path / "source.png"
    Image.new("RGB", (20, 10), "red").save(source)
    result = edit_image(
        "session-1",
        "source.png",
        [{"type": "resize", "width": 8, "height": 6}, {"type": "grayscale"}],
    )
    assert (result["width"], result["height"]) == (8, 6)
    assert gallery("session-1")["count"] == 1


def test_pdf_extraction_creates_markdown_artifact(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from pypdf import PdfWriter
    from api.ingestion import extract_pdf

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with (tmp_path / "input.pdf").open("wb") as output:
        writer.write(output)
    result = extract_pdf("session-1", "input.pdf")
    assert result["pages"] == 1
    assert result["artifact"]["path"].endswith("-extracted.md")


def test_pdf_form_fill_updates_known_field(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, RectangleObject, TextStringObject
    from api.ingestion import fill_pdf_form

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject("name"),
            NameObject("/V"): TextStringObject(""),
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): RectangleObject([10, 10, 200, 40]),
        }
    )
    reference = writer._add_object(field)
    page[NameObject("/Annots")] = ArrayObject([reference])
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject(
        {NameObject("/Fields"): ArrayObject([reference])}
    )
    with (tmp_path / "form.pdf").open("wb") as output:
        writer.write(output)

    result = fill_pdf_form("session-1", "form.pdf", {"name": "Matthew"})
    filled = PdfReader(tmp_path / result["artifact"]["path"])
    assert filled.get_fields()["name"]["/V"] == "Matthew"


def test_youtube_ingestion_uses_fixed_yt_dlp_command(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    from api import ingestion

    def fake_run(command, **_kwargs):
        template = Path(command[command.index("--output") + 1])
        (template.parent / "transcript.en.vtt").write_text(
            "WEBVTT\n\n00:00.000 --> 00:01.000\nHello world\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"id": "abc123", "title": "Example"}),
            stderr="",
        )

    monkeypatch.setattr(ingestion.subprocess, "run", fake_run)
    result = ingestion.ingest_youtube("session-1", "https://youtu.be/abc123")
    assert result["video_id"] == "abc123"
    content = (tmp_path / result["artifact"]["path"]).read_text()
    assert "Hello world" in content


def test_youtube_ingestion_rejects_non_youtube_hosts():
    from api.ingestion import IngestionError, _youtube_url

    try:
        _youtube_url("https://example.com/watch?v=abc")
    except IngestionError as exc:
        assert "youtube.com" in str(exc)
    else:
        raise AssertionError("non-YouTube host was accepted")


def test_content_http_contract_routes_through_profile_scope(monkeypatch):
    from fastapi_app.main import create_app
    from fastapi_app.request_context import (
        RequestIdentity,
        require_identity,
        require_mutation_identity,
    )

    monkeypatch.setattr(
        "api.ingestion.extract_pdf",
        lambda session_id, path: {"ok": True, "session_id": session_id, "path": path},
    )
    identity = RequestIdentity(session_cookie=None, profile="default", auth_enabled=False)
    app = create_app()
    app.dependency_overrides[require_identity] = lambda: identity
    app.dependency_overrides[require_mutation_identity] = lambda: identity
    response = TestClient(app).post(
        "/api/content/pdf/extract",
        json={"session_id": "session-1", "path": "document.pdf"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True,
        "session_id": "session-1",
        "path": "document.pdf",
    }
