"""
Vision model integration for image content ingestion.

Uses MiniCPM-V (via Ollama) to generate text descriptions of images,
which are then embedded and stored in the vector database alongside
text content. This makes images searchable by their content.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


class VisionDescriber:
    """Generate text descriptions of images using Ollama vision models."""

    def __init__(self, ollama_url: str = "http://127.0.0.1:11434", model: str = "minicpm-v", timeout: float = 60.0) -> None:
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def describe_image(self, image_path: str, prompt: str = "") -> str:
        """Generate a detailed text description of an image.

        Args:
            image_path: Path to the image file
            prompt: Custom prompt. If empty, uses default description prompt.

        Returns:
            Text description of the image content.
        """
        if not prompt:
            prompt = (
                "Describe this image in detail for a knowledge base. Include: "
                "1) What the image shows (objects, people, scenes) "
                "2) Any text visible in the image (OCR) "
                "3) Technical details if it's a diagram, schematic, or chart "
                "4) Context about what this image might be used for "
                "Be thorough but factual. If you're unsure, say so."
            )

        try:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
        except Exception as exc:
            logger.error("Failed to read image %s: %s", image_path, exc)
            return ""

        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "images": [image_data],
            "stream": False,
            "options": {"temperature": 0.1},  # Low temperature for factual descriptions
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("response", "").strip()
        except Exception as exc:
            logger.error("Vision description failed for %s: %s", image_path, exc)
            return ""

    def is_available(self) -> bool:
        """Check if the vision model is available on Ollama."""
        try:
            req = urllib.request.Request(
                f"{self.ollama_url}/api/tags",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                return any(self.model in m for m in models)
        except Exception:
            return False


def is_image_file(filepath: str) -> bool:
    """Check if a file is an image that can be processed by the vision model."""
    ext = Path(filepath).suffix.lower().lstrip(".")
    return ext in {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"}


# Prompts for different types of image description
IMAGE_PROMPTS = {
    "default": (
        "Describe this image in detail for a knowledge base. Include: "
        "1) What the image shows (objects, people, scenes) "
        "2) Any text visible in the image (OCR) "
        "3) Technical details if it's a diagram, schematic, or chart "
        "4) Context about what this image might be used for "
        "Be thorough but factual. If you're unsure, say so."
    ),
    "schematic": (
        "This appears to be a technical schematic or diagram. Describe: "
        "1) The type of diagram (circuit, flowchart, architecture, etc.) "
        "2) All labeled components and their connections "
        "3) Any values, ratings, or specifications shown "
        "4) The overall system or circuit being depicted "
    ),
    "screenshot": (
        "This appears to be a screenshot. Describe: "
        "1) What application or interface is shown "
        "2) Key UI elements and their state "
        "3) Any text, data, or error messages visible "
        "4) What the user was likely doing "
    ),
    "photo": (
        "Describe this photograph for a knowledge base. Include: "
        "1) Subject matter (people, objects, environment) "
        "2) Setting and context "
        "3) Notable details, text, or markings "
        "4) Estimated time period if historical "
    ),
}