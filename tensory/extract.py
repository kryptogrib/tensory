"""Context-aware LLM extraction for tensory.

Extracts atomic claims and entity relations from raw text, filtered
through the user's research goal (Context). The LLM is called only
on write — search/collisions are algorithmic.

Two modes:
1. With Context: claims extracted relative to research goal + domain
2. Without Context: generic extraction (all claims, no relevance filter)

References:
- Claim extraction + temporal bounds: Graphiti prompts/extract_edges.py
- ClaimType + confidence: Hindsight CARA (arxiv.org/abs/2512.12818)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, cast, runtime_checkable

from tensory.models import Claim, ClaimType, Context, EntityRelation, MemoryType
from tensory.prompts import PROCEDURAL_INDUCTION_PROMPT

logger = logging.getLogger(__name__)


@runtime_checkable
class LLMProtocol(Protocol):
    """Protocol for LLM text completion.

    Any async callable that takes a prompt and returns text works.
    Compatible with OpenAI, Anthropic, local models, etc.
    """

    async def __call__(self, prompt: str) -> str: ...


# ── Prompts ───────────────────────────────────────────────────────────────

EXTRACT_PROMPT_WITH_CONTEXT = """You are extracting information for a specific research goal.

RESEARCH GOAL: {goal}
DOMAIN: {domain}

Extract claims from this text that are RELEVANT to the research goal above.
Skip information that is not relevant to the goal.

IMPORTANT temporal rules:
- If the text has a date header (e.g. "[Session 3 — 2:00 pm on 25 May, 2023]"), use it as the reference date
- Convert ALL relative time references ("last Saturday", "yesterday", "next month") to absolute dates using the reference date
- Include the specific date IN the claim text itself, e.g. "On 20 May 2023, Melanie ran a charity race"
- The "temporal" field should contain the exact date in YYYY-MM-DD format when possible

For each claim, also:
- Rate its relevance to the research goal (0.0-1.0)
- Identify entity relationships (who did what to whom)

TEXT:
{text}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "claims": [
    {{
      "text": "atomic claim WITH dates included in the text",
      "type": "fact|experience|observation|opinion",
      "entities": ["Entity1", "Entity2"],
      "temporal": "YYYY-MM-DD or descriptive date, never null if any time reference exists",
      "confidence": 0.0-1.0,
      "relevance": 0.0-1.0
    }}
  ],
  "relations": [
    {{
      "from": "Entity1",
      "to": "Entity2",
      "type": "PARTNERED_WITH|INVESTED_IN|DEPARTED_FROM|...",
      "fact": "human readable description"
    }}
  ]
}}

If nothing is relevant to the research goal, return {{"claims": [], "relations": []}}"""

EXTRACT_PROMPT_GENERIC = """Extract all factual claims and entity relationships from this text.

IMPORTANT temporal rules:
- If the text has a date header (e.g. "[Session 3 — 2:00 pm on 25 May, 2023]"), use it as the reference date
- Convert ALL relative time references ("last Saturday", "yesterday", "next month") to absolute dates using the reference date
- Include the specific date IN the claim text itself, e.g. "On 20 May 2023, Melanie ran a charity race"
- The "temporal" field should contain the exact date in YYYY-MM-DD format when possible

TEXT:
{text}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "claims": [
    {{
      "text": "atomic claim WITH dates included in the text",
      "type": "fact|experience|observation|opinion",
      "entities": ["Entity1", "Entity2"],
      "temporal": "YYYY-MM-DD or descriptive date, never null if any time reference exists",
      "confidence": 0.0-1.0,
      "relevance": 1.0
    }}
  ],
  "relations": [
    {{
      "from": "Entity1",
      "to": "Entity2",
      "type": "PARTNERED_WITH|INVESTED_IN|DEPARTED_FROM|...",
      "fact": "human readable description"
    }}
  ]
}}

If no claims can be extracted, return {{"claims": [], "relations": []}}"""


# ── Public API ────────────────────────────────────────────────────────────


async def extract_claims(
    text: str,
    llm: LLMProtocol,
    *,
    context: Context | None = None,
) -> tuple[list[Claim], list[EntityRelation]]:
    """Extract claims and relations from raw text using LLM.

    Args:
        text: Raw text to extract from.
        llm: LLM callable (prompt → response text).
        context: Optional research goal for context-aware extraction.

    Returns:
        Tuple of (claims, relations).
    """
    if context:
        prompt = EXTRACT_PROMPT_WITH_CONTEXT.format(
            goal=context.goal,
            domain=context.domain,
            text=text,
        )
    else:
        prompt = EXTRACT_PROMPT_GENERIC.format(text=text)

    try:
        response = await llm(prompt)
        return _parse_extraction(response, context_id=context.id if context else None)
    except Exception as exc:
        logger.warning("LLM extraction failed: %s", exc)
        return [], []


async def extract_procedural(
    text: str,
    llm: LLMProtocol,
) -> list[Claim]:
    """Extract procedural skills from raw text using LLM.

    Uses Skill-MDP framework (ProcMEM): trigger + steps + termination.

    Args:
        text: Raw experience text to extract skills from.
        llm: LLM callable (prompt → response text).

    Returns:
        List of Claim objects with memory_type=PROCEDURAL.
    """
    prompt = PROCEDURAL_INDUCTION_PROMPT.format(text=text)

    try:
        response = await llm(prompt)
        return _parse_procedural_extraction(response)
    except Exception as exc:
        logger.warning("Procedural extraction failed: %s", exc)
        return []


def _parse_procedural_extraction(response: str) -> list[Claim]:
    """Parse LLM response into procedural Claim objects."""
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse procedural extraction response as JSON")
        return []

    skills: list[Claim] = []
    for item in cast(list[dict[str, Any]], data.get("skills", [])):
        trigger = str(item.get("trigger", "")).strip()
        steps_raw = item.get("steps", [])
        steps = [str(s).strip() for s in steps_raw if s] if isinstance(steps_raw, list) else []

        if not trigger and not steps:
            continue  # skip empty skills

        termination = str(item.get("termination_condition", "")).strip() or None
        outcome = str(item.get("expected_outcome", "")).strip()

        # Build descriptive text for embedding/FTS search
        steps_text = "; ".join(steps) if steps else "no steps"
        claim_text = f"Skill: when {trigger}, do: {steps_text}"
        if outcome:
            claim_text += f" → {outcome}"

        skills.append(
            Claim(
                text=claim_text,
                type=ClaimType.EXPERIENCE,  # procedural derived from experience
                memory_type=MemoryType.PROCEDURAL,
                trigger=trigger,
                steps=steps,
                termination_condition=termination,
                entities=_parse_list(item.get("entities", [])),
                confidence=0.5,  # new skills start at neutral confidence
            )
        )

    return skills


# ── Parsing ───────────────────────────────────────────────────────────────


def _parse_extraction(
    response: str,
    context_id: str | None = None,
) -> tuple[list[Claim], list[EntityRelation]]:
    """Parse LLM JSON response into Claim and EntityRelation objects."""
    # Strip markdown code blocks if present
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```json and ```)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM extraction response as JSON")
        return [], []

    claims: list[Claim] = []
    claims_data = cast(list[dict[str, Any]], data.get("claims", []))
    for item in claims_data:
        claim_text = str(item.get("text", "")).strip()
        if not claim_text:
            continue

        claim_type = _parse_claim_type(str(item.get("type", "fact")))
        temporal_val: Any = item.get("temporal")
        claims.append(
            Claim(
                text=claim_text,
                type=claim_type,
                entities=_parse_list(item.get("entities", [])),
                temporal=str(temporal_val) if temporal_val else None,
                confidence=_parse_float(item.get("confidence"), default=1.0),
                relevance=_parse_float(item.get("relevance"), default=1.0),
                context_id=context_id,
            )
        )

    relations: list[EntityRelation] = []
    rels_data = cast(list[dict[str, Any]], data.get("relations", []))
    for rel in rels_data:
        from_entity = str(rel.get("from", "")).strip()
        to_entity = str(rel.get("to", "")).strip()
        if not from_entity or not to_entity:
            continue

        relations.append(
            EntityRelation(
                from_entity=from_entity,
                to_entity=to_entity,
                rel_type=str(rel.get("type", "RELATED_TO")),
                fact=str(rel.get("fact", "")),
            )
        )

    return claims, relations


def _parse_claim_type(value: str) -> ClaimType:
    """Parse claim type string, defaulting to FACT."""
    try:
        return ClaimType(value.lower().strip())
    except ValueError:
        return ClaimType.FACT


def _parse_float(value: object, *, default: float = 1.0) -> float:
    """Safely parse a float from LLM response."""
    if value is None:
        return default
    try:
        result = float(str(value))
        return max(0.0, min(1.0, result))
    except (ValueError, TypeError):
        return default


def _parse_list(value: Any) -> list[str]:
    """Safely parse a list of strings from LLM response."""
    if not isinstance(value, list):
        return []
    typed_list = cast(list[Any], value)
    return [str(v).strip() for v in typed_list if v]
