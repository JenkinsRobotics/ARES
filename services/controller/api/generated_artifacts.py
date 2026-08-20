"""Image editing and visual reports over the shared artifact store."""

from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any

from api.workspace_artifacts import list_artifacts, read_workspace_bytes, write_artifact


class GeneratedArtifactError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def image_editor_health_probe() -> None:
    try:
        import PIL  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Image editing requires Pillow") from exc


def gallery(session_id: str) -> dict[str, Any]:
    inventory = list_artifacts(session_id)
    images = [
        item
        for item in inventory["items"]
        if str(item.get("media_type") or "").startswith("image/")
    ]
    return {"count": len(images), "items": images}


def edit_image(
    session_id: str,
    path: str,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    image_editor_health_probe()
    from PIL import Image, ImageOps

    max_pixels = 40_000_000

    def enforce_size(candidate) -> None:
        if candidate.width < 1 or candidate.height < 1:
            raise GeneratedArtifactError("Image dimensions must be positive")
        if candidate.width * candidate.height > max_pixels:
            raise GeneratedArtifactError("Image exceeds the 40 megapixel limit", 413)

    if not 1 <= len(operations) <= 10:
        raise GeneratedArtifactError("Provide between 1 and 10 image operations")
    try:
        image = Image.open(BytesIO(read_workspace_bytes(session_id, path)))
        enforce_size(image)
        image.load()
    except Exception as exc:
        raise GeneratedArtifactError(f"Could not read image: {type(exc).__name__}") from exc
    for operation in operations:
        name = str(operation.get("type") or "").strip().lower()
        if name == "resize":
            width = int(operation.get("width") or 0)
            height = int(operation.get("height") or 0)
            if not 1 <= width <= 10_000 or not 1 <= height <= 10_000:
                raise GeneratedArtifactError("Resize dimensions must be between 1 and 10000")
            image = image.resize((width, height))
        elif name == "rotate":
            image = image.rotate(float(operation.get("degrees") or 0), expand=True)
        elif name == "crop":
            box = tuple(int(operation.get(key) or 0) for key in ("left", "top", "right", "bottom"))
            if box[2] <= box[0] or box[3] <= box[1]:
                raise GeneratedArtifactError("Crop requires right > left and bottom > top")
            image = image.crop(box)
        elif name == "grayscale":
            image = ImageOps.grayscale(image)
        else:
            raise GeneratedArtifactError(f"Unsupported image operation: {name or '(empty)'}")
        enforce_size(image)
    suffix = ".jpg" if Path(path).suffix.lower() in {".jpg", ".jpeg"} else ".png"
    if suffix == ".jpg" and image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    output = BytesIO()
    image.save(output, format="JPEG" if suffix == ".jpg" else "PNG")
    artifact = write_artifact(session_id, f"{Path(path).stem}-edited{suffix}", output.getvalue())
    return {"ok": True, "width": image.width, "height": image.height, "artifact": artifact}


def create_visual_report(
    session_id: str,
    *,
    title: str,
    summary: str,
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    clean_title = str(title or "").strip()
    if not clean_title:
        raise GeneratedArtifactError("Report title is required")
    if len(sections) > 50:
        raise GeneratedArtifactError("A report can contain at most 50 sections")
    section_html = []
    for section in sections:
        heading = escape(str(section.get("heading") or "").strip())
        body = escape(str(section.get("body") or "").strip()).replace("\n", "<br>")
        if heading or body:
            section_html.append(f"<section><h2>{heading}</h2><p>{body}</p></section>")
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{escape(clean_title)}</title><style>
body{{font:16px/1.6 system-ui,sans-serif;max-width:900px;margin:auto;padding:48px 24px;color:#202124}}
header{{border-bottom:3px solid #6750a4;margin-bottom:32px}}h1{{font-size:2.5rem;line-height:1.1}}
h2{{margin-top:32px;color:#503a86}}p{{white-space:normal}}section{{break-inside:avoid}}
@media print{{body{{padding:0}}}}
</style></head><body><header><h1>{escape(clean_title)}</h1><p>{escape(str(summary or ""))}</p></header>
{''.join(section_html)}</body></html>"""
    artifact = write_artifact(
        session_id,
        f"{clean_title}-report.html",
        document.encode("utf-8"),
    )
    return {"ok": True, "sections": len(section_html), "artifact": artifact}


__all__ = [
    "GeneratedArtifactError",
    "create_visual_report",
    "edit_image",
    "gallery",
    "image_editor_health_probe",
]
