"""Tests for ExtractionGate — smart throttling for LLM extraction."""

from __future__ import annotations

import aiosqlite
import pytest

from tensory.extraction_gate import ExtractionGate


@pytest.fixture
async def db() -> aiosqlite.Connection:
    """In-memory SQLite connection."""
    conn = await aiosqlite.connect(":memory:")
    yield conn  # type: ignore[misc]
    await conn.close()


@pytest.fixture
async def gate(db: aiosqlite.Connection) -> ExtractionGate:
    """ExtractionGate with table created."""
    g = ExtractionGate(db)
    await g.ensure_table()
    return g


# ── Length gate ──────────────────────────────────────────────────────────


async def test_short_transcript_skipped(gate: ExtractionGate) -> None:
    """Transcript shorter than MIN_TRANSCRIPT_LENGTH (200) is skipped."""
    result = await gate.should_extract("sess-1", "hi there", "/project")
    assert result is False


async def test_normal_transcript_passes(gate: ExtractionGate) -> None:
    """Transcript >= 200 chars on first call passes (no prior state)."""
    transcript = "a" * 250
    result = await gate.should_extract("sess-1", transcript, "/project")
    assert result is True


async def test_exactly_at_threshold(gate: ExtractionGate) -> None:
    """Transcript exactly at threshold passes."""
    transcript = "x" * 200
    result = await gate.should_extract("sess-1", transcript, "/project")
    assert result is True


# ── Overlap gate ─────────────────────────────────────────────────────────


async def test_identical_transcript_skipped(gate: ExtractionGate) -> None:
    """Same transcript repeated → overlap > 0.7 → skipped."""
    transcript = "The quick brown fox jumps over the lazy dog. " * 10
    # First extraction
    assert await gate.should_extract("sess-1", transcript, "/proj") is True
    await gate.record_extraction("sess-1", transcript, "/proj")

    # Same transcript again
    assert await gate.should_extract("sess-1", transcript, "/proj") is False


async def test_extended_transcript_passes(gate: ExtractionGate) -> None:
    """Transcript with significant new content passes overlap check."""
    base = "The quick brown fox jumps over the lazy dog. " * 5
    extended = base + "This is completely new content about a different topic. " * 10

    assert await gate.should_extract("sess-1", base, "/proj") is True
    await gate.record_extraction("sess-1", base, "/proj")

    # Extended transcript should pass (enough new content)
    assert await gate.should_extract("sess-1", extended, "/proj") is True


async def test_slightly_different_transcript_skipped(gate: ExtractionGate) -> None:
    """Transcript with minimal changes is still skipped."""
    base = "The quick brown fox jumps over the lazy dog. " * 10
    tweaked = base + " ok"  # trivial addition

    assert await gate.should_extract("sess-1", base, "/proj") is True
    await gate.record_extraction("sess-1", base, "/proj")

    assert await gate.should_extract("sess-1", tweaked, "/proj") is False


# ── Per-session independence ─────────────────────────────────────────────


async def test_different_sessions_independent(gate: ExtractionGate) -> None:
    """Session A overlap does not block session B."""
    transcript = "Shared content between sessions for testing overlap. " * 8

    # Session A records extraction
    assert await gate.should_extract("sess-A", transcript, "/proj") is True
    await gate.record_extraction("sess-A", transcript, "/proj")

    # Session A is blocked (same transcript)
    assert await gate.should_extract("sess-A", transcript, "/proj") is False

    # Session B is NOT blocked (different session, no prior state)
    assert await gate.should_extract("sess-B", transcript, "/proj") is True


# ── Fail-open behavior ──────────────────────────────────────────────────


async def test_gate_error_fails_open(gate: ExtractionGate) -> None:
    """Gate errors default to 'extract' (fail-open)."""
    # Drop the table to cause an error during overlap check
    await gate._db.execute("DROP TABLE extraction_state")
    await gate._db.commit()

    transcript = "a" * 300
    # Should return True (fail-open) despite DB error
    result = await gate.should_extract("sess-1", transcript, "/proj")
    assert result is True


# ── State persistence ────────────────────────────────────────────────────


async def test_record_extraction_updates_state(gate: ExtractionGate) -> None:
    """After record_extraction, state is persisted with hash and timestamp."""
    transcript = "Some meaningful content for extraction gate testing. " * 5
    await gate.record_extraction("sess-1", transcript, "/proj")

    async with gate._db.execute(
        "SELECT session_id, project_path, last_shingles, last_len, extracted_at "
        "FROM extraction_state WHERE session_id = ?",
        ("sess-1",),
    ) as cursor:
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == "sess-1"
    assert row[1] == "/proj"
    assert row[2] is not None  # shingles stored
    assert row[3] == len(transcript)
    assert row[4] is not None  # timestamp stored


async def test_record_updates_on_conflict(gate: ExtractionGate) -> None:
    """Second record_extraction for same session updates existing row."""
    t1 = "First transcript content for testing gate persistence. " * 5
    t2 = "Second completely different transcript for testing updates. " * 5

    await gate.record_extraction("sess-1", t1, "/proj")
    await gate.record_extraction("sess-1", t2, "/proj")

    async with gate._db.execute(
        "SELECT last_len FROM extraction_state WHERE session_id = ?",
        ("sess-1",),
    ) as cursor:
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == len(t2)  # updated to second transcript length


# ── ENV overrides ────────────────────────────────────────────────────────


async def test_env_min_transcript_override(
    gate: ExtractionGate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TENSORY_MIN_TRANSCRIPT env var overrides default threshold."""
    monkeypatch.setenv("TENSORY_MIN_TRANSCRIPT", "500")

    # 300 chars — above default 200 but below override 500
    transcript = "a" * 300
    assert await gate.should_extract("sess-1", transcript, "/proj") is False

    # 600 chars — above override
    transcript = "a" * 600
    assert await gate.should_extract("sess-1", transcript, "/proj") is True


async def test_env_overlap_threshold_override(
    gate: ExtractionGate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TENSORY_OVERLAP_THRESHOLD env var overrides default threshold."""
    monkeypatch.setenv("TENSORY_OVERLAP_THRESHOLD", "0.95")

    transcript = "The quick brown fox jumps over the lazy dog. " * 10
    await gate.record_extraction("sess-1", transcript, "/proj")

    # Same transcript but with stricter threshold (0.95)
    # Identical transcript has Jaccard=1.0, still blocked
    assert await gate.should_extract("sess-1", transcript, "/proj") is False

    # With very lax threshold, same transcript would pass
    monkeypatch.setenv("TENSORY_OVERLAP_THRESHOLD", "1.1")
    assert await gate.should_extract("sess-1", transcript, "/proj") is True
