"""Smart context formatter — structures search results for LLM consumption.

Transforms a flat list of SearchResult into LLM-ready text with:
- Conditional entity grouping (when diversity is high)
- Chronological ordering within entity groups
- Temporal validity annotations [Jan 2024→] or [Jan-Mar 2024, OUTDATED]
- Superseding markers with cross-references

Format B (compact):
    [Alice]
    1. Alice worked at Acme [Jan-Mar 2024, OUTDATED]
    2. Alice joined Beta Inc [Jun 2024→, replaces #1]

    [Bob]
    3. Bob met Alice at conference [Feb 2024]
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from tensory.models import Claim, SearchResult

# Ungrouped claims bucket key
_GENERAL = "_general"


def format_context(
    results: list[SearchResult],
    *,
    min_entities_for_grouping: int = 4,
) -> str:
    """Format search results as structured LLM-ready context.

    Groups claims by primary entity when the result set contains many
    distinct entities (> min_entities_for_grouping). Otherwise returns
    a flat numbered list with temporal annotations.

    Args:
        results: Search results from store.search().
        min_entities_for_grouping: Minimum unique primary entities
            to trigger grouped output. Default 4 (>3 unique entities).

    Returns:
        Formatted string ready to inject into an LLM prompt.
    """
    if not results:
        return "(no relevant claims found)"

    # Build a global index: claim.id → flat position (for superseding refs)
    id_to_index: dict[str, int] = {}
    for i, r in enumerate(results, 1):
        if r.claim.id:
            id_to_index[r.claim.id] = i

    # Determine unique primary entities
    unique_entities = _unique_primary_entities(results)

    if len(unique_entities) >= min_entities_for_grouping:
        return _format_grouped(results, id_to_index)
    return _format_flat(results, id_to_index)


def _unique_primary_entities(results: list[SearchResult]) -> set[str]:
    """Count unique primary entities (first entity of each claim)."""
    entities: set[str] = set()
    for r in results:
        if r.claim.entities:
            entities.add(r.claim.entities[0])
    return entities


def _format_flat(
    results: list[SearchResult],
    id_to_index: dict[str, int],
) -> str:
    """Flat numbered list with temporal annotations."""
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        annotation = _build_annotation(r, id_to_index)
        suffix = f" [{annotation}]" if annotation else ""
        lines.append(f"{i}. {r.claim.text}{suffix}")
    return "\n".join(lines)


def _format_grouped(
    results: list[SearchResult],
    id_to_index: dict[str, int],
) -> str:
    """Entity-grouped format with chronological ordering within groups."""
    # Group by primary entity
    groups: dict[str, list[tuple[int, SearchResult]]] = defaultdict(list)
    for i, r in enumerate(results, 1):
        key = r.claim.entities[0] if r.claim.entities else _GENERAL
        groups[key].append((i, r))

    # Sort within each group chronologically
    for key in groups:
        groups[key].sort(key=lambda pair: _sort_key(pair[1]))

    # Render groups — named entities first, _general last
    sections: list[str] = []
    entity_keys = sorted(
        (k for k in groups if k != _GENERAL),
        key=lambda k: -max(r.score for _, r in groups[k]),
    )
    if _GENERAL in groups:
        entity_keys.append(_GENERAL)

    for key in entity_keys:
        header = f"[{key}]" if key != _GENERAL else "[General]"
        lines: list[str] = [header]
        for idx, r in groups[key]:
            annotation = _build_annotation(r, id_to_index)
            suffix = f" [{annotation}]" if annotation else ""
            lines.append(f"{idx}. {r.claim.text}{suffix}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _build_annotation(
    result: SearchResult,
    id_to_index: dict[str, int],
) -> str:
    """Build temporal + status annotation for a single claim.

    Examples:
        "Jan 2024→"              — valid from, still active
        "Jan-Mar 2024, OUTDATED" — valid range, superseded
        "Q1 2024"                — from temporal field
        "May 2024"               — fallback to created_at
    """
    claim = result.claim
    parts: list[str] = []

    # Temporal range
    temporal_str = _format_temporal(claim)
    if temporal_str:
        parts.append(temporal_str)

    # Superseded marker
    if claim.superseded_by is not None:
        parts.append("OUTDATED")
        # Find the replacement in the result set
        replacement_idx = id_to_index.get(claim.superseded_by)
        if replacement_idx is not None:
            parts.append(f"replaced by #{replacement_idx}")

    return ", ".join(parts)


def _format_temporal(claim: Claim) -> str:
    """Format temporal information from the richest available source."""
    if claim.valid_from and claim.valid_to:
        return f"{_fmt_date(claim.valid_from)}-{_fmt_date(claim.valid_to)}"
    if claim.valid_from:
        return f"{_fmt_date(claim.valid_from)}→"
    if claim.temporal:
        return claim.temporal
    if claim.created_at:
        return _fmt_date(claim.created_at)
    return ""


def _fmt_date(dt: datetime) -> str:
    """Short month-year format: 'Jan 2024'."""
    return dt.strftime("%b %Y")


def _sort_key(result: SearchResult) -> datetime:
    """Sort key for chronological ordering within entity groups."""
    claim = result.claim
    if claim.valid_from:
        return claim.valid_from
    if claim.created_at:
        return claim.created_at
    return datetime(1970, 1, 1, tzinfo=UTC)
