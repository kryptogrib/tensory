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


# ── Deterministic ClaimType → MemoryType mapping ────────────────────────
# Grounded in PlugMem's cognitive taxonomy (arXiv:2603.03296):
#   experience → episodic  (events with time/place context)
#   fact/observation/opinion → semantic (stable knowledge)
# Procedural is set explicitly by extract_procedural(), not this map.
CLAIM_TO_MEMORY_TYPE: dict[ClaimType, MemoryType] = {
    ClaimType.EXPERIENCE: MemoryType.EPISODIC,
    ClaimType.FACT: MemoryType.SEMANTIC,
    ClaimType.OBSERVATION: MemoryType.SEMANTIC,
    ClaimType.OPINION: MemoryType.SEMANTIC,
}


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

VERBATIM PRESERVATION — these rules override all others:
- NEVER paraphrase proper nouns, specific objects, locations, or quantities
- Use the speaker's EXACT words for: country names, city names, people's names, numbers, colors, specific objects
- If the text says "Sweden", write "Sweden" — NOT "home country" or "Scandinavian country"
- If the text says "sunset", write "sunset" — NOT "nature-inspired" or "landscape"
- If the text says "3 children", write "3 children" — NOT "kids" or "younger children"
- If the text says "rainbow flag", write "rainbow flag" — NOT "symbol" or "flag"
- When in doubt, QUOTE the original words rather than summarize

WRONG: "Melanie painted a nature-inspired artwork"
RIGHT: "Melanie painted a sunset"

WRONG: "Caroline moved from her home country"
RIGHT: "Caroline moved from Sweden"

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

VERBATIM PRESERVATION — these rules override all others:
- NEVER paraphrase proper nouns, specific objects, locations, or quantities
- Use the speaker's EXACT words for: country names, city names, people's names, numbers, colors, specific objects
- If the text says "Sweden", write "Sweden" — NOT "home country" or "Scandinavian country"
- If the text says "sunset", write "sunset" — NOT "nature-inspired" or "landscape"
- If the text says "3 children", write "3 children" — NOT "kids" or "younger children"
- If the text says "rainbow flag", write "rainbow flag" — NOT "symbol" or "flag"
- When in doubt, QUOTE the original words rather than summarize

WRONG: "Melanie painted a nature-inspired artwork"
RIGHT: "Melanie painted a sunset"

WRONG: "Caroline moved from her home country"
RIGHT: "Caroline moved from Sweden"

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


async def extract_long(
    text: str,
    llm: LLMProtocol,
    *,
    max_segments: int,
    context: Context | None = None,
    document_date: str | None = None,
) -> tuple[list[Claim], list[EntityRelation]]:
    """Extract claims from long text via topic segmentation + parallel extraction.

    Pipeline:
    1. segment_text() → list of (title, section_text)
    2. For each section: prepend header → extract_claims() in parallel
    3. Deduplicate entity names across sections
    4. Aggregate all claims + relations

    Falls back to paragraph splitting if segmentation fails.

    Args:
        text: Long text to extract from.
        llm: LLM callable.
        max_segments: Maximum sections to split into.
        context: Optional research goal.
        document_date: Date of the document (preserved in section headers).
    """
    import asyncio

    from tensory.chunking import (
        build_section_header,
        deduplicate_entities,
        normalize_entity,
        segment_text,
    )

    # Step 1: Segment text into thematic sections
    sections = await segment_text(text, llm, max_segments=max_segments)

    if not sections:
        return await extract_claims(text, llm, context=context)

    # Step 2: Build extraction tasks with section headers
    total = len(sections)

    async def _extract_section(
        index: int, title: str, section_text: str
    ) -> tuple[list[Claim], list[EntityRelation]]:
        header = build_section_header(
            document_date=document_date,
            section_index=index,
            total_sections=total,
            section_title=title,
        )
        augmented_text = f"{header}\n\n{section_text}"
        return await extract_claims(augmented_text, llm, context=context)

    # Step 3: Parallel extraction
    tasks = [_extract_section(i, title, sec_text) for i, (title, sec_text) in enumerate(sections)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Step 4: Aggregate results
    all_claims: list[Claim] = []
    all_relations: list[EntityRelation] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("Section extraction failed: %s", result)
            continue
        claims, relations = result
        all_claims.extend(claims)
        all_relations.extend(relations)

    # Step 5: Deduplicate entity names across sections
    all_entity_names: list[str] = []
    for claim in all_claims:
        all_entity_names.extend(claim.entities)
    canonical = deduplicate_entities(all_entity_names)
    canonical_map: dict[str, str] = {}
    for name in canonical:
        canonical_map[normalize_entity(name)] = name
    for claim in all_claims:
        claim.entities = [canonical_map.get(normalize_entity(e), e) for e in claim.entities]

    return all_claims, all_relations


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
        steps_raw: Any = item.get("steps", [])
        if isinstance(steps_raw, list):
            steps: list[str] = [str(s).strip() for s in cast(list[object], steps_raw) if s]
        else:
            steps = []

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

        # Filter out short-term claims (ephemeral noise)
        durability = str(item.get("durability", "long-term")).lower().strip()
        if durability == "short-term":
            logger.debug("Skipping short-term claim: %s", claim_text[:80])
            continue

        claim_type = _parse_claim_type(str(item.get("type", "fact")))
        memory_type = CLAIM_TO_MEMORY_TYPE.get(claim_type, MemoryType.SEMANTIC)
        temporal_val: Any = item.get("temporal")
        claims.append(
            Claim(
                text=claim_text,
                type=claim_type,
                memory_type=memory_type,
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
