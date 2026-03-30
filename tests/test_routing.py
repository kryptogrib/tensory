"""Tests for query-type classification and memory-type routing."""

from __future__ import annotations

from tensory.models import MemoryType
from tensory.routing import classify_query


class TestClassifyQuery:
    """classify_query maps natural language to MemoryType or None."""

    def test_when_question_returns_episodic(self) -> None:
        assert classify_query("When did Alice move to Berlin?") == MemoryType.EPISODIC

    def test_what_date_returns_episodic(self) -> None:
        assert classify_query("What date was the meeting?") == MemoryType.EPISODIC

    def test_how_long_ago_returns_episodic(self) -> None:
        assert classify_query("How long ago did Bob join?") == MemoryType.EPISODIC

    def test_since_when_returns_episodic(self) -> None:
        assert classify_query("Since when has she been working there?") == MemoryType.EPISODIC

    def test_what_happened_returns_episodic(self) -> None:
        assert classify_query("What happened at the conference?") == MemoryType.EPISODIC

    def test_what_year_returns_episodic(self) -> None:
        assert classify_query("What year did they launch?") == MemoryType.EPISODIC

    def test_how_to_returns_procedural(self) -> None:
        assert classify_query("How to deploy the service?") == MemoryType.PROCEDURAL

    def test_steps_to_returns_procedural(self) -> None:
        assert classify_query("What are the steps to configure auth?") == MemoryType.PROCEDURAL

    def test_procedure_for_returns_procedural(self) -> None:
        assert classify_query("What is the procedure for onboarding?") == MemoryType.PROCEDURAL

    def test_instructions_returns_procedural(self) -> None:
        assert classify_query("Give me instructions for setup") == MemoryType.PROCEDURAL

    def test_factual_question_returns_none(self) -> None:
        assert classify_query("What is EigenLayer?") is None

    def test_who_question_returns_none(self) -> None:
        assert classify_query("Who is the CEO of Acme?") is None

    def test_generic_question_returns_none(self) -> None:
        assert classify_query("Tell me about DeFi trends") is None

    def test_empty_query_returns_none(self) -> None:
        assert classify_query("") is None

    def test_case_insensitive_when(self) -> None:
        assert classify_query("WHEN did it happen?") == MemoryType.EPISODIC

    def test_case_insensitive_how_to(self) -> None:
        assert classify_query("HOW TO do this?") == MemoryType.PROCEDURAL
