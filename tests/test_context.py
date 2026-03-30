"""Tests for context formatting — structured LLM-ready output from search results."""

from __future__ import annotations

from datetime import UTC, datetime

from tensory.context import format_context
from tensory.models import Claim, ClaimType, MemoryType, SearchResult


def _make_claim(
    text: str,
    *,
    id: str = "",
    entities: list[str] | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    superseded_by: str | None = None,
    superseded_at: datetime | None = None,
    created_at: datetime | None = None,
    temporal: str | None = None,
    claim_type: ClaimType = ClaimType.FACT,
    memory_type: MemoryType = MemoryType.SEMANTIC,
) -> Claim:
    return Claim(
        id=id or text[:8],
        text=text,
        entities=entities or [],
        valid_from=valid_from,
        valid_to=valid_to,
        superseded_by=superseded_by,
        superseded_at=superseded_at,
        created_at=created_at or datetime(2024, 1, 1, tzinfo=UTC),
        temporal=temporal,
        type=claim_type,
        memory_type=memory_type,
    )


def _make_result(claim: Claim, score: float = 0.9) -> SearchResult:
    return SearchResult(claim=claim, score=score)


class TestFlatFormat:
    """When unique entities <= 3, output is a flat numbered list."""

    def test_empty_results_returns_placeholder(self) -> None:
        result = format_context([])
        assert "no relevant" in result.lower()

    def test_single_claim_flat(self) -> None:
        claim = _make_claim("Alice works at Acme", entities=["Alice", "Acme"])
        result = format_context([_make_result(claim)])
        assert "1." in result
        assert "Alice works at Acme" in result

    def test_temporal_annotation_from_valid_from(self) -> None:
        claim = _make_claim(
            "Alice joined Acme",
            entities=["Alice"],
            valid_from=datetime(2024, 3, 15, tzinfo=UTC),
        )
        result = format_context([_make_result(claim)])
        assert "Mar 2024" in result

    def test_temporal_range_when_valid_to_set(self) -> None:
        claim = _make_claim(
            "Alice worked at Acme",
            entities=["Alice"],
            valid_from=datetime(2024, 1, 1, tzinfo=UTC),
            valid_to=datetime(2024, 6, 1, tzinfo=UTC),
        )
        result = format_context([_make_result(claim)])
        assert "Jan 2024" in result
        assert "Jun 2024" in result

    def test_outdated_marker_when_superseded(self) -> None:
        claim = _make_claim(
            "Alice works at Acme",
            entities=["Alice"],
            superseded_by="new_claim_id",
            superseded_at=datetime(2024, 6, 1, tzinfo=UTC),
        )
        result = format_context([_make_result(claim)])
        assert "OUTDATED" in result

    def test_fallback_to_temporal_field(self) -> None:
        claim = _make_claim("Meeting in Q1", temporal="Q1 2024")
        result = format_context([_make_result(claim)])
        assert "Q1 2024" in result

    def test_fallback_to_created_at(self) -> None:
        claim = _make_claim(
            "Something happened",
            created_at=datetime(2024, 5, 20, tzinfo=UTC),
        )
        result = format_context([_make_result(claim)])
        assert "May 2024" in result

    def test_three_entities_stays_flat(self) -> None:
        results = [
            _make_result(_make_claim("A fact", entities=["Alice"])),
            _make_result(_make_claim("B fact", entities=["Bob"])),
            _make_result(_make_claim("C fact", entities=["Charlie"])),
        ]
        result = format_context(results)
        assert "[Alice]" not in result
        assert "1." in result


class TestGroupedFormat:
    """When unique entities > 3, output is grouped by primary entity."""

    def test_groups_by_primary_entity(self) -> None:
        results = [
            _make_result(_make_claim("A works at X", entities=["Alice", "X"])),
            _make_result(_make_claim("B works at Y", entities=["Bob", "Y"])),
            _make_result(_make_claim("C works at Z", entities=["Charlie", "Z"])),
            _make_result(_make_claim("D works at W", entities=["Diana", "W"])),
        ]
        result = format_context(results)
        assert "[Alice]" in result
        assert "[Bob]" in result
        assert "[Charlie]" in result
        assert "[Diana]" in result

    def test_chronological_order_within_group(self) -> None:
        results = [
            _make_result(
                _make_claim(
                    "Alice at Beta",
                    entities=["Alice"],
                    valid_from=datetime(2024, 6, 1, tzinfo=UTC),
                ),
                score=0.8,
            ),
            _make_result(
                _make_claim(
                    "Alice at Acme",
                    entities=["Alice"],
                    valid_from=datetime(2024, 1, 1, tzinfo=UTC),
                ),
                score=0.9,
            ),
            _make_result(_make_claim("Bob fact", entities=["Bob"])),
            _make_result(_make_claim("Charlie fact", entities=["Charlie"])),
            _make_result(_make_claim("Diana fact", entities=["Diana"])),
        ]
        result = format_context(results)
        acme_pos = result.index("Alice at Acme")
        beta_pos = result.index("Alice at Beta")
        assert acme_pos < beta_pos

    def test_superseded_claim_shows_replacement_ref(self) -> None:
        old_claim = _make_claim(
            "Alice works at Acme",
            id="old_id",
            entities=["Alice"],
            superseded_by="new_id",
            superseded_at=datetime(2024, 6, 1, tzinfo=UTC),
            valid_from=datetime(2024, 1, 1, tzinfo=UTC),
        )
        new_claim = _make_claim(
            "Alice works at Beta",
            id="new_id",
            entities=["Alice"],
            valid_from=datetime(2024, 6, 1, tzinfo=UTC),
        )
        results = [
            _make_result(old_claim, score=0.7),
            _make_result(new_claim, score=0.9),
            _make_result(_make_claim("Bob fact", entities=["Bob"])),
            _make_result(_make_claim("Charlie fact", entities=["Charlie"])),
            _make_result(_make_claim("Diana fact", entities=["Diana"])),
        ]
        result = format_context(results)
        assert "OUTDATED" in result
        assert "replaced by" in result.lower()

    def test_claims_without_entities_go_to_general(self) -> None:
        results = [
            _make_result(_make_claim("No entity claim", entities=[])),
            _make_result(_make_claim("A fact", entities=["Alice"])),
            _make_result(_make_claim("B fact", entities=["Bob"])),
            _make_result(_make_claim("C fact", entities=["Charlie"])),
            _make_result(_make_claim("D fact", entities=["Diana"])),
        ]
        result = format_context(results)
        assert "No entity claim" in result


class TestGroupingThreshold:
    """The min_entities_for_grouping parameter controls flat vs grouped."""

    def test_force_grouping_with_low_threshold(self) -> None:
        results = [
            _make_result(_make_claim("A fact", entities=["Alice"])),
            _make_result(_make_claim("B fact", entities=["Bob"])),
        ]
        result = format_context(results, min_entities_for_grouping=1)
        assert "[Alice]" in result

    def test_force_flat_with_high_threshold(self) -> None:
        results = [
            _make_result(_make_claim("A fact", entities=["Alice"])),
            _make_result(_make_claim("B fact", entities=["Bob"])),
            _make_result(_make_claim("C fact", entities=["Charlie"])),
            _make_result(_make_claim("D fact", entities=["Diana"])),
            _make_result(_make_claim("E fact", entities=["Eve"])),
        ]
        result = format_context(results, min_entities_for_grouping=100)
        assert "[Alice]" not in result
