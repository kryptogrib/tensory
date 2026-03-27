"""Ingest LoCoMo conversation into Tensory.

Ingests by session (not per-turn) for efficiency:
- ~20 LLM calls (Haiku) instead of ~300
- LLM sees full session context for better extraction
- Tracks dia_id → episode_id mapping for retrieval evaluation

Usage:
    store = await Tensory.create(...)
    mapping = await ingest_conversation(store, conversation)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from benchmarks.locomo.data import Conversation
from tensory.models import Context
from tensory.store import Tensory

logger = logging.getLogger(__name__)


@dataclass
class IngestStats:
    """Statistics from ingestion."""

    sessions_ingested: int = 0
    total_claims: int = 0
    total_entities: int = 0
    total_collisions: int = 0
    # dia_id → episode_id for retrieval evaluation
    dia_to_episode: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    errors: list[str] = field(default_factory=lambda: list[str]())


async def ingest_conversation(
    store: Tensory,
    conversation: Conversation,
    *,
    context: Context | None = None,
) -> IngestStats:
    """Ingest all sessions of a LoCoMo conversation into Tensory.

    Each session is ingested as one episode via store.add().
    Tracks the mapping from dia_id to episode_id for later
    retrieval evaluation (recall@k on evidence turns).

    Args:
        store: Initialized Tensory instance with LLM configured.
        conversation: Parsed LoCoMo conversation.
        context: Optional research context for extraction.

    Returns:
        IngestStats with counts and dia_id mapping.
    """
    stats = IngestStats()

    for session in conversation.sessions:
        session_text = session.to_text()
        source = f"locomo:{conversation.sample_id}:session_{session.session_num}"

        logger.info(
            "Ingesting session %d (%d turns, %d chars)",
            session.session_num,
            len(session.turns),
            len(session_text),
        )

        try:
            result = await store.add(
                session_text,
                source=source,
                context=context,
            )

            stats.sessions_ingested += 1
            stats.total_claims += len(result.claims)
            stats.total_entities += len(result.new_entities)
            stats.total_collisions += len(result.collisions)

            # Map each dia_id in this session to the episode
            for dia_id in session.dia_ids:
                stats.dia_to_episode[dia_id] = result.episode_id

            logger.info(
                "  → %d claims, %d entities, %d collisions",
                len(result.claims),
                len(result.new_entities),
                len(result.collisions),
            )

        except Exception as exc:
            error_msg = f"Session {session.session_num}: {exc}"
            stats.errors.append(error_msg)
            logger.error("Failed to ingest session %d: %s", session.session_num, exc)

    return stats
