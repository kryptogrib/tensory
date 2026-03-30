"""Query-type classification for memory-type routing.

Maps natural language queries to MemoryType using regex heuristics.
No LLM calls — pure pattern matching on question words.

Returns None when no specific type is detected (search all types).
"""

from __future__ import annotations

import re

from tensory.models import MemoryType

_EPISODIC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bwhen\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+date\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+year\b", re.IGNORECASE),
    re.compile(r"\bhow\s+long\s+ago\b", re.IGNORECASE),
    re.compile(r"\bsince\s+when\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+happened\b", re.IGNORECASE),
]

_PROCEDURAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bhow\s+to\b", re.IGNORECASE),
    re.compile(r"\bsteps?\s+to\b", re.IGNORECASE),
    re.compile(r"\bprocedure\s+for\b", re.IGNORECASE),
    re.compile(r"\binstructions?\s+for\b", re.IGNORECASE),
]


def classify_query(query: str) -> MemoryType | None:
    """Classify a query into a MemoryType for search routing.

    Returns MemoryType.EPISODIC for temporal questions,
    MemoryType.PROCEDURAL for how-to questions,
    or None for general queries (search all types).

    Uses regex heuristics — no LLM calls.
    """
    if not query.strip():
        return None

    for pattern in _EPISODIC_PATTERNS:
        if pattern.search(query):
            return MemoryType.EPISODIC

    for pattern in _PROCEDURAL_PATTERNS:
        if pattern.search(query):
            return MemoryType.PROCEDURAL

    return None
