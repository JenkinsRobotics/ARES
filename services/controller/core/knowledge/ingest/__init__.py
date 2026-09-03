"""Ingestion pipelines for the ARES Knowledge Base."""

from .pipeline import ingest
from .pdf import ingest_pdf
from .web import ingest_url
from .youtube import ingest_youtube
from .markdown import ingest_file, ingest_directory

__all__ = ["ingest", "ingest_pdf", "ingest_url", "ingest_youtube", "ingest_file", "ingest_directory"]