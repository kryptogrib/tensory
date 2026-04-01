"""Extraction gate — decides whether LLM extraction should run for a transcript.

Adapted from Claude Code's dual-threshold session memory pattern.
Three-stage cheapest-first evaluation:
1. Length check (O(1))
2. MinHash overlap check (O(n shingles))
3. Pass → extract

Fail-open: any gate error defaults to "extract" so data is never lost.
State is per-session in SQLite table ``extraction_state``.
"""

from __future__ import annotations

import json
import logging
import os
import time

import aiosqlite

from tensory.dedup import jaccard, shingle

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS extraction_state (
    session_id    TEXT PRIMARY KEY,
    project_path  TEXT NOT NULL,
    last_shingles TEXT,
    last_len      INTEGER DEFAULT 0,
    extracted_at  REAL,
    created_at    REAL NOT NULL DEFAULT (unixepoch('now'))
)
"""


def _min_transcript_length() -> int:
    """Minimum transcript length to trigger extraction (ENV override)."""
    return int(os.environ.get("TENSORY_MIN_TRANSCRIPT", "200"))


def _overlap_threshold() -> float:
    """Jaccard overlap above which extraction is skipped (ENV override).

    Intentionally lower than dedup.py's 0.9 claim-level threshold.
    Transcripts are longer and structurally overlap more (shared preamble,
    system prompts), so a lower bar catches --continue duplicates while
    allowing genuinely extended sessions.
    """
    return float(os.environ.get("TENSORY_OVERLAP_THRESHOLD", "0.7"))


class ExtractionGate:
    """Decides whether LLM extraction should run for a given transcript.

    Usage::

        gate = ExtractionGate(db)
        await gate.ensure_table()

        if await gate.should_extract(session_id, transcript, project_path):
            result = await store.add(transcript, episode_id=eid)
            await gate.record_extraction(session_id, transcript, project_path)
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def ensure_table(self) -> None:
        """Create extraction_state table if it does not exist."""
        await self._db.execute(_CREATE_TABLE_SQL)
        await self._db.commit()

    async def should_extract(
        self,
        session_id: str,
        transcript: str,
        project_path: str,
    ) -> bool:
        """Three-stage gate (cheapest first).

        1. Length: ``len(transcript) < MIN_TRANSCRIPT_LENGTH`` → False
        2. Overlap: Jaccard with last transcript > threshold → False
        3. Pass → True

        Fail-open: returns True on any internal error so extraction
        is never silently skipped due to gate bugs.
        """
        try:
            # Stage 1: length check
            if len(transcript) < _min_transcript_length():
                logger.debug(
                    "[gate] session=%s len=%d → skip (too short)",
                    session_id,
                    len(transcript),
                )
                return False

            # Stage 2: overlap check against last extracted transcript
            overlap = await self._compute_overlap(session_id, transcript)
            if overlap is not None and overlap > _overlap_threshold():
                logger.debug(
                    "[gate] session=%s len=%d overlap=%.2f → skip (overlap)",
                    session_id,
                    len(transcript),
                    overlap,
                )
                return False

            logger.debug(
                "[gate] session=%s len=%d overlap=%s → extract",
                session_id,
                len(transcript),
                f"{overlap:.2f}" if overlap is not None else "n/a",
            )
            return True

        except Exception:
            logger.warning(
                "[gate] error evaluating session=%s, defaulting to extract",
                session_id,
                exc_info=True,
            )
            return True

    async def record_extraction(
        self,
        session_id: str,
        transcript: str,
        project_path: str,
    ) -> None:
        """Update state after successful extraction."""
        shingles = shingle(transcript)
        shingles_json = json.dumps(sorted(shingles))
        await self._db.execute(
            """INSERT INTO extraction_state
                   (session_id, project_path, last_shingles, last_len, extracted_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                   project_path = excluded.project_path,
                   last_shingles = excluded.last_shingles,
                   last_len = excluded.last_len,
                   extracted_at = excluded.extracted_at""",
            (
                session_id,
                project_path,
                shingles_json,
                len(transcript),
                time.time(),
                time.time(),
            ),
        )
        await self._db.commit()

    # ── Private helpers ──────────────────────────────────────────────────

    async def _compute_overlap(
        self,
        session_id: str,
        transcript: str,
    ) -> float | None:
        """Compute Jaccard overlap with previous transcript for this session.

        Returns None if no previous extraction exists (first time).
        """
        async with self._db.execute(
            "SELECT last_shingles FROM extraction_state WHERE session_id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None or row[0] is None:
            return None

        prev_shingles: frozenset[str] = frozenset(json.loads(row[0]))
        curr_shingles = shingle(transcript)
        return jaccard(prev_shingles, curr_shingles)
