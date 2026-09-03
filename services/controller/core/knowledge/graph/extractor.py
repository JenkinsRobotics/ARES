"""Entity and relationship extraction for GraphRAG.

Uses a local LLM (Ollama) to extract entities and relationships from text chunks.
Falls back to spaCy NLP extraction if LLM is unavailable (FastGraphRAG mode).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Sequence

from ..config import KBConfig

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    name: str
    entity_type: str
    description: str = ""
    source: str = ""


@dataclass
class Relationship:
    source_entity: str
    target_entity: str
    relation_type: str
    description: str = ""
    source: str = ""
    confidence: float = 1.0


@dataclass
class ExtractionResult:
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)


def extract_with_llm(text: str, source: str, config: KBConfig) -> ExtractionResult:
    """Extract entities and relationships using a local LLM via Ollama."""
    prompt = f"""Extract entities and relationships from the following text. Return JSON only.

Text:
{text[:2000]}

Return a JSON object with this exact structure:
{{
  "entities": [
    {{"name": "Entity Name", "type": "person|organization|concept|technology|location|event|project|other", "description": "brief description"}}
  ],
  "relationships": [
    {{"source": "Entity A", "target": "Entity B", "relation": "relates_to|developed_by|used_in|part_of|causes|depends_on|located_in|created_by|mentions", "description": "brief description"}}
  ]
}}

Only extract entities and relationships that are clearly present in the text. Be precise."""

    payload = json.dumps({
        "model": config.entity_extraction_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{config.ollama_base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            response_text = data.get("response", "")
            # Parse the JSON response
            # Ollama with format=json should return valid JSON, but be defensive
            try:
                parsed = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to find JSON in the response
                match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group())
                else:
                    return ExtractionResult()

            result = ExtractionResult()
            for ent in parsed.get("entities", []):
                result.entities.append(Entity(
                    name=ent.get("name", "").strip(),
                    entity_type=ent.get("type", "other").strip().lower(),
                    description=ent.get("description", "").strip(),
                    source=source,
                ))
            for rel in parsed.get("relationships", []):
                result.relationships.append(Relationship(
                    source_entity=rel.get("source", "").strip(),
                    target_entity=rel.get("target", "").strip(),
                    relation_type=rel.get("relation", "relates_to").strip().lower(),
                    description=rel.get("description", "").strip(),
                    source=source,
                    confidence=float(rel.get("confidence", 1.0)),
                ))
            return result
    except Exception as exc:
        logger.warning("LLM extraction failed for %s: %s", source, exc)
        return ExtractionResult()


def extract_with_nlp(text: str, source: str) -> ExtractionResult:
    """FastGraphRAG mode: extract entities using spaCy NLP (no LLM needed)."""
    try:
        import spacy
    except ImportError:
        logger.debug("spaCy not available for NLP extraction")
        return ExtractionResult()

    try:
        nlp = spacy.load("en_core_web_sm")
    except Exception:
        logger.debug("spaCy model not loaded")
        return ExtractionResult()

    doc = nlp(text[:5000])
    result = ExtractionResult()

    seen_entities = set()
    for ent in doc.ents:
        name = ent.text.strip()
        if not name or len(name) < 2 or name.lower() in seen_entities:
            continue
        seen_entities.add(name.lower())
        entity_type = {
            "PERSON": "person",
            "ORG": "organization",
            "GPE": "location",
            "LOC": "location",
            "EVENT": "event",
            "PRODUCT": "technology",
            "WORK_OF_ART": "concept",
            "LAW": "concept",
            "LANGUAGE": "concept",
        }.get(ent.label_, "other")
        result.entities.append(Entity(
            name=name,
            entity_type=entity_type,
            source=source,
        ))

    # Simple co-occurrence relationships (entities in same sentence)
    for sent in doc.sents:
        sent_entities = [e for e in result.entities if e.name in sent.text]
        for i, e1 in enumerate(sent_entities):
            for e2 in sent_entities[i+1:]:
                if e1.name != e2.name:
                    result.relationships.append(Relationship(
                        source_entity=e1.name,
                        target_entity=e2.name,
                        relation_type="mentions",
                        source=source,
                        confidence=0.5,
                    ))

    return result


def extract(text: str, source: str, config: KBConfig) -> ExtractionResult:
    """Extract entities and relationships. Tries LLM first, falls back to NLP."""
    if not text or not text.strip():
        return ExtractionResult()

    # Try LLM extraction first
    result = extract_with_llm(text, source, config)
    if result.entities:
        return result

    # Fall back to NLP
    return extract_with_nlp(text, source)