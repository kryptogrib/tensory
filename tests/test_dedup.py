"""Tests for dedup.py — entropy-gated MinHash/LSH deduplication."""

from __future__ import annotations

from tensory.dedup import MinHashDedup, _jaccard, _shannon_entropy, _shingle

# ── Entropy ───────────────────────────────────────────────────────────────


def test_entropy_empty_string() -> None:
    assert _shannon_entropy("") == 0.0


def test_entropy_single_char() -> None:
    assert _shannon_entropy("aaaa") == 0.0


def test_entropy_high_for_natural_text() -> None:
    entropy = _shannon_entropy("EigenLayer announced a new partnership with Google Cloud")
    assert entropy > 3.0  # natural English has ~4 bits entropy


def test_entropy_low_for_repetitive() -> None:
    entropy = _shannon_entropy("aaa bbb")
    assert entropy < 2.5  # below threshold


# ── Shingles + Jaccard ────────────────────────────────────────────────────


def test_shingle_produces_ngrams() -> None:
    shingles = _shingle("hello world")
    assert len(shingles) > 0
    assert all(len(s) == 3 for s in shingles)


def test_jaccard_identical() -> None:
    a = _shingle("hello world")
    assert _jaccard(a, a) == 1.0


def test_jaccard_disjoint() -> None:
    a = _shingle("hello world")
    b = _shingle("xyz abc def")
    assert _jaccard(a, b) < 0.3


def test_jaccard_similar() -> None:
    a = _shingle("EigenLayer has 50 team members")
    b = _shingle("EigenLayer has 55 team members")
    assert _jaccard(a, b) > 0.7


# ── MinHashDedup ──────────────────────────────────────────────────────────


def test_dedup_blocks_exact_duplicate() -> None:
    dedup = MinHashDedup()
    existing = ["EigenLayer announced a partnership with Google Cloud"]
    assert dedup.is_duplicate(
        "EigenLayer announced a partnership with Google Cloud",
        existing,
    )


def test_dedup_blocks_fuzzy_duplicate() -> None:
    dedup = MinHashDedup(jaccard_threshold=0.75)  # lowered for real-world fuzzy matching
    existing = [
        "EigenLayer announced a major partnership with Google Cloud for restaking infrastructure"
    ]
    assert dedup.is_duplicate(
        "EigenLayer announced a major partnership with Google Cloud for restaking services",
        existing,
    )


def test_dedup_allows_different_claims() -> None:
    dedup = MinHashDedup()
    existing = ["EigenLayer has 50 team members"]
    assert not dedup.is_duplicate(
        "Bitcoin price reached new all-time high of 100k",
        existing,
    )


def test_dedup_empty_existing() -> None:
    dedup = MinHashDedup()
    assert not dedup.is_duplicate("Any text", [])


def test_dedup_low_entropy_exact_only() -> None:
    """Low entropy text uses exact match, not fuzzy."""
    dedup = MinHashDedup()
    existing = ["aaa bbb"]
    # Exact match works
    assert dedup.is_duplicate("aaa bbb", existing)
    # Near-match doesn't work for low entropy
    assert not dedup.is_duplicate("aaa bbc", existing)


def test_find_duplicates_returns_indices() -> None:
    dedup = MinHashDedup()
    existing = [
        "Unique claim one",
        "EigenLayer has 50 team members working on restaking",
        "Unique claim three",
        "EigenLayer has 50 team members working on restaking protocol",
    ]
    indices = dedup.find_duplicates(
        "EigenLayer has 50 team members working on restaking",
        existing,
    )
    assert 1 in indices  # exact match
