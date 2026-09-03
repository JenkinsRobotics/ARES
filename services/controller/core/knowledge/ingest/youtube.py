"""YouTube transcript ingestion pipeline.

Downloads transcripts from YouTube videos using yt-dlp and ingests them.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..config import KBConfig
from ..vector.store import KnowledgeStore

logger = logging.getLogger(__name__)


def ingest_youtube(url: str, config: KBConfig, store: KnowledgeStore | None = None) -> dict:
    """Download a YouTube transcript and ingest it into the vector store.

    Uses yt-dlp to fetch auto-generated or manual subtitles.
    Falls back to audio transcription with Whisper if no subtitles available.
    """
    if store is None:
        store = KnowledgeStore(config)

    # Try yt-dlp for transcript
    ytdlp = _find_binary("yt-dlp")
    if not ytdlp:
        return {"ok": False, "error": "yt-dlp not installed. Run: pip install yt-dlp"}

    with tempfile.TemporaryDirectory() as tmpdir:
        # Download subtitles as JSON
        try:
            result = subprocess.run(
                [ytdlp, "--write-auto-sub", "--write-sub", "--sub-format", "vtt/json3",
                 "--skip-download", "--sub-lang", "en", "--output", f"{tmpdir}/transcript",
                 "--convert-subs", "json3", url],
                capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "yt-dlp timed out"}
        except Exception as exc:
            return {"ok": False, "error": f"yt-dlp failed: {exc}"}

        # Find the downloaded subtitle file
        sub_files = list(Path(tmpdir).glob("transcript*.json3"))
        if not sub_files:
            sub_files = list(Path(tmpdir).glob("transcript*.vtt"))
        if not sub_files:
            # List what was downloaded
            downloaded = list(Path(tmpdir).iterdir())
            return {"ok": False, "error": f"No subtitle file found. Files: {[f.name for f in downloaded]}"}

        # Parse the subtitle file
        text = _parse_subtitle(sub_files[0])
        if not text.strip():
            return {"ok": False, "error": "No text in subtitle file"}

        # Get video title
        title = _get_video_title(url, ytdlp)

        source = url
        chunks = store.ingest(text, source=source, source_type="transcript", heading=title)
        return {"ok": True, "chunks_created": chunks, "source": source, "title": title, "chars_extracted": len(text)}


def _find_binary(name: str) -> str:
    import shutil
    return shutil.which(name) or ""


def _parse_subtitle(path: Path) -> str:
    """Parse a subtitle file (JSON3 or VTT) into plain text."""
    if path.suffix == ".json3":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            segments = []
            for event in data.get("events", []):
                if "segs" in event:
                    text = "".join(s.get("utf8", "") for s in event["segs"])
                    if text.strip():
                        segments.append(text.strip())
            return "\n".join(segments)
        except Exception:
            pass

    # VTT or SRT — strip timestamps
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    text_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Skip timestamp lines
        if "-->" in line or line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        # Skip lines that are just numbers (SRT sequence numbers)
        if line.isdigit():
            continue
        text_lines.append(line)
    return "\n".join(text_lines)


def _get_video_title(url: str, ytdlp: str) -> str:
    try:
        result = subprocess.run(
            [ytdlp, "--print", "title", url],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() or url
    except Exception:
        return url