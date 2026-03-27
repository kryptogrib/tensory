"""Download and parse LoCoMo benchmark data.

Fetches locomo10.json from the official Snap Research repo,
parses it into typed dataclasses for ingestion and evaluation.

Data format: 10 conversations, each with ~300 turns across ~20 sessions,
plus QA pairs (5 categories) with evidence turn IDs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
CACHE_PATH = Path("benchmarks/locomo/.cache/locomo10.json")

# QA category names from the LoCoMo paper (ACL 2024)
CATEGORY_NAMES: dict[int, str] = {
    1: "single-hop",
    2: "multi-hop",
    3: "temporal",
    4: "open-domain",
    5: "adversarial",
}


@dataclass
class Turn:
    """Single dialogue turn."""

    speaker: str
    dia_id: str  # e.g. "D1:3" = session 1, turn 3
    text: str


@dataclass
class Session:
    """One conversation session (a group of turns on one date)."""

    session_num: int
    date_time: str
    turns: list[Turn] = field(default_factory=list)

    def to_text(self) -> str:
        """Serialize session for ingestion into Tensory."""
        lines = [f"[Session {self.session_num} — {self.date_time}]"]
        for turn in self.turns:
            lines.append(f"{turn.speaker}: {turn.text}")
        return "\n".join(lines)

    @property
    def dia_ids(self) -> list[str]:
        """All turn IDs in this session."""
        return [t.dia_id for t in self.turns]


@dataclass
class QAItem:
    """One QA evaluation item."""

    question: str
    answer: str  # "unanswerable" for adversarial
    evidence: list[str]  # dia_ids referencing turns
    category: int  # 1-5

    @property
    def is_adversarial(self) -> bool:
        """Whether this is an adversarial (category 5) question."""
        return self.category == 5

    @property
    def category_name(self) -> str:
        """Human-readable category name."""
        return CATEGORY_NAMES.get(self.category, f"unknown-{self.category}")


@dataclass
class Conversation:
    """Parsed LoCoMo conversation with sessions and QA items."""

    sample_id: str
    speaker_a: str
    speaker_b: str
    sessions: list[Session] = field(default_factory=list)
    qa_items: list[QAItem] = field(default_factory=list)


def parse_conversation(raw: dict[str, Any]) -> Conversation:  # noqa: C901
    """Parse a raw LoCoMo JSON entry into typed Conversation."""
    conv_data = raw.get("conversation", {})
    speaker_a = conv_data.get("speaker_a", "")
    speaker_b = conv_data.get("speaker_b", "")

    sessions: list[Session] = []
    session_pattern = re.compile(r"^session_(\d+)$")

    for key, value in conv_data.items():
        match = session_pattern.match(key)
        if match and isinstance(value, list):
            num = int(match.group(1))
            date_key = f"session_{num}_date_time"
            date_time = conv_data.get(date_key, "")

            turns = []
            for turn_data in value:
                if isinstance(turn_data, dict) and "text" in turn_data:
                    turns.append(
                        Turn(
                            speaker=turn_data.get("speaker", ""),
                            dia_id=turn_data.get("dia_id", ""),
                            text=turn_data.get("text", ""),
                        )
                    )

            if turns:
                sessions.append(Session(session_num=num, date_time=date_time, turns=turns))

    sessions.sort(key=lambda s: s.session_num)

    qa_items: list[QAItem] = []
    for qa in raw.get("qa", []):
        category = qa.get("category", 0)
        if category == 5:
            answer = "unanswerable"
        else:
            answer = qa.get("answer", "")

        qa_items.append(
            QAItem(
                question=qa.get("question", ""),
                answer=answer,
                evidence=qa.get("evidence", []),
                category=category,
            )
        )

    return Conversation(
        sample_id=raw.get("sample_id", ""),
        speaker_a=speaker_a,
        speaker_b=speaker_b,
        sessions=sessions,
        qa_items=qa_items,
    )


async def load_locomo(conversation_idx: int = 0) -> Conversation:
    """Download (with cache) and parse one LoCoMo conversation."""
    if CACHE_PATH.exists():
        data = json.loads(CACHE_PATH.read_text())
    else:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(LOCOMO_URL)
            resp.raise_for_status()
            data = resp.json()

        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False))

    return parse_conversation(data[conversation_idx])
