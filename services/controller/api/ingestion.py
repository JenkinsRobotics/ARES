"""PDF and YouTube ingestion built on workspace artifacts."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import parse_qs, urlparse

from api.workspace_artifacts import read_workspace_bytes, write_artifact


class IngestionError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def pdf_health_probe() -> None:
    try:
        import pypdf  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("PDF support requires pypdf") from exc


def youtube_health_probe() -> None:
    try:
        import yt_dlp  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("YouTube ingestion requires yt-dlp") from exc


def extract_pdf(session_id: str, path: str) -> dict[str, Any]:
    pdf_health_probe()
    from pypdf import PdfReader

    if Path(path).suffix.lower() != ".pdf":
        raise IngestionError("PDF extraction requires a .pdf file")
    try:
        reader = PdfReader(BytesIO(read_workspace_bytes(session_id, path)))
        if len(reader.pages) > 500:
            raise IngestionError("PDF exceeds the 500 page limit", 413)
        pages = [str(page.extract_text() or "").strip() for page in reader.pages]
        fields = reader.get_fields() or {}
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError(f"Could not read PDF: {type(exc).__name__}") from exc
    text = "\n\n".join(
        f"## Page {index}\n\n{content}" for index, content in enumerate(pages, 1)
    )
    artifact = write_artifact(
        session_id,
        f"{Path(path).stem}-extracted.md",
        text.encode("utf-8"),
    )
    return {
        "ok": True,
        "pages": len(pages),
        "characters": len(text),
        "fields": sorted(str(name) for name in fields),
        "artifact": artifact,
    }


def fill_pdf_form(session_id: str, path: str, fields: dict[str, Any]) -> dict[str, Any]:
    pdf_health_probe()
    from pypdf import PdfReader, PdfWriter

    if Path(path).suffix.lower() != ".pdf":
        raise IngestionError("PDF form filling requires a .pdf file")
    if not fields or len(fields) > 200:
        raise IngestionError("Provide between 1 and 200 PDF field values")
    clean = {str(key)[:256]: str(value)[:10_000] for key, value in fields.items()}
    try:
        reader = PdfReader(BytesIO(read_workspace_bytes(session_id, path)))
        available = set((reader.get_fields() or {}).keys())
        unknown = sorted(set(clean) - available)
        if unknown:
            raise IngestionError(f"Unknown PDF fields: {', '.join(unknown[:10])}")
        writer = PdfWriter()
        writer.append(reader)
        for page in writer.pages:
            writer.update_page_form_field_values(page, clean, auto_regenerate=False)
        output = BytesIO()
        writer.write(output)
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError(f"Could not fill PDF: {type(exc).__name__}") from exc
    artifact = write_artifact(session_id, f"{Path(path).stem}-filled.pdf", output.getvalue())
    return {"ok": True, "updated_fields": sorted(clean), "artifact": artifact}


def _youtube_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
    }:
        raise IngestionError("Use an https://youtube.com or https://youtu.be URL")
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise IngestionError("YouTube URLs cannot contain credentials or custom ports")
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif parsed.path.startswith(("/shorts/", "/embed/")):
        video_id = parsed.path.strip("/").split("/", 1)[1]
    else:
        video_id = (parse_qs(parsed.query).get("v") or [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", video_id):
        raise IngestionError("YouTube URL is missing a valid video ID")
    return f"https://www.youtube.com/watch?v={video_id}"


def _vtt_text(content: str) -> str:
    lines = []
    previous = None
    for raw in content.splitlines():
        line = re.sub(r"<[^>]+>", "", raw).strip()
        if not line or line == "WEBVTT" or "-->" in line or line.startswith(("Kind:", "Language:")):
            continue
        if line != previous:
            lines.append(line)
            previous = line
    return "\n".join(lines)


def ingest_youtube(session_id: str, url: str, languages: list[str] | None = None) -> dict[str, Any]:
    youtube_health_probe()
    safe_url = _youtube_url(url)
    requested = [re.sub(r"[^A-Za-z0-9._-]", "", item) for item in (languages or ["en.*", "en"])]
    requested = [item for item in requested if item][:5] or ["en"]
    with tempfile.TemporaryDirectory(prefix="ares-youtube-") as temporary:
        template = str(Path(temporary) / "transcript.%(ext)s")
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-format",
            "vtt",
            "--sub-langs",
            ",".join(requested),
            "--print-json",
            "--output",
            template,
            safe_url,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise IngestionError("YouTube transcript request timed out", 504) from exc
        if completed.returncode != 0:
            message = completed.stderr.strip().splitlines()[-1:] or ["transcript unavailable"]
            raise IngestionError(f"YouTube transcript failed: {message[0]}", 502)
        files = sorted(Path(temporary).glob("*.vtt"))
        if not files:
            raise IngestionError("No transcript is available for this video", 404)
        if files[0].stat().st_size > 10 * 1024 * 1024:
            raise IngestionError("YouTube transcript exceeds the 10 MB limit", 413)
        text = _vtt_text(files[0].read_text(encoding="utf-8", errors="replace"))
        if not text:
            raise IngestionError("The returned transcript was empty", 502)
        metadata = {}
        for line in reversed(completed.stdout.splitlines()):
            try:
                metadata = json.loads(line)
                break
            except ValueError:
                continue
    video_id = str(metadata.get("id") or "youtube")
    title = str(metadata.get("title") or video_id)
    body = f"# {title}\n\nSource: {safe_url}\n\n{text}\n"
    artifact = write_artifact(session_id, f"youtube-{video_id}.md", body.encode("utf-8"))
    return {
        "ok": True,
        "video_id": video_id,
        "title": title,
        "characters": len(text),
        "artifact": artifact,
    }


__all__ = [
    "IngestionError",
    "extract_pdf",
    "fill_pdf_form",
    "ingest_youtube",
    "pdf_health_probe",
    "youtube_health_probe",
]
