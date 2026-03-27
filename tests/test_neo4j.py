"""Tests for Neo4jBackend — unit tests with mocked Neo4j driver.

These tests verify the Cypher queries and Protocol compliance
without requiring a running Neo4j instance.

For integration tests with real Neo4j, use:
    docker run -d -p 7687:7687 -e NEO4J_AUTH=neo4j/test neo4j:latest
    pytest tests/test_neo4j.py -k integration --neo4j-uri bolt://localhost:7687
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tensory.graph import GraphBackend, Neo4jBackend, SQLiteGraphBackend


# ── Protocol compliance ──────────────────────────────────────────────────


def test_neo4j_backend_satisfies_protocol() -> None:
    """Neo4jBackend structurally satisfies GraphBackend Protocol."""
    # Can't instantiate without neo4j driver, but we can check the class
    assert hasattr(Neo4jBackend, "add_entity")
    assert hasattr(Neo4jBackend, "add_edge")
    assert hasattr(Neo4jBackend, "traverse")
    assert hasattr(Neo4jBackend, "get_shared_entities")
    assert hasattr(Neo4jBackend, "find_path")
    assert hasattr(Neo4jBackend, "close")


def test_sqlite_backend_satisfies_protocol() -> None:
    """SQLiteGraphBackend satisfies GraphBackend Protocol (sanity check)."""
    assert hasattr(SQLiteGraphBackend, "add_entity")
    assert hasattr(SQLiteGraphBackend, "add_edge")
    assert hasattr(SQLiteGraphBackend, "traverse")
    assert hasattr(SQLiteGraphBackend, "get_shared_entities")
    assert hasattr(SQLiteGraphBackend, "find_path")
    assert hasattr(SQLiteGraphBackend, "close")


# ── Mock-based tests for Neo4jBackend ────────────────────────────────────


class MockRecord:
    """Simulates a neo4j Record."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]


class MockResult:
    """Simulates a neo4j Result."""

    def __init__(self, records: list[MockRecord]) -> None:
        self._records = records
        self._index = 0

    async def single(self) -> MockRecord | None:
        return self._records[0] if self._records else None

    def __aiter__(self) -> MockResult:
        self._index = 0
        return self

    async def __anext__(self) -> MockRecord:
        if self._index >= len(self._records):
            raise StopAsyncIteration
        record = self._records[self._index]
        self._index += 1
        return record


class MockSession:
    """Simulates a neo4j AsyncSession."""

    def __init__(self) -> None:
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self._responses: list[MockResult] = []

    def set_response(self, records: list[MockRecord]) -> None:
        self._responses.append(MockResult(records))

    async def run(self, query: str, **kwargs: Any) -> MockResult:
        self.queries.append((query, kwargs))
        if self._responses:
            return self._responses.pop(0)
        return MockResult([])

    async def __aenter__(self) -> MockSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


class MockDriver:
    """Simulates neo4j AsyncGraphDatabase.driver."""

    def __init__(self) -> None:
        self.session_mock = MockSession()

    def session(self, **kwargs: Any) -> MockSession:
        return self.session_mock

    async def close(self) -> None:
        pass


@pytest.fixture
def neo4j_backend() -> Neo4jBackend:
    """Create Neo4jBackend with mocked driver."""
    with patch("tensory.graph.Neo4jBackend.__init__", lambda self, *a, **kw: None):
        backend = Neo4jBackend.__new__(Neo4jBackend)
        backend._driver = MockDriver()
        backend._database = "neo4j"
        return backend


# ── add_entity ────────────────────────────────────────────────────────────


async def test_add_entity_merge(neo4j_backend: Neo4jBackend) -> None:
    """add_entity uses MERGE to upsert."""
    mock_driver: MockDriver = neo4j_backend._driver  # type: ignore[assignment]
    mock_driver.session_mock.set_response([MockRecord({"id": "abc123"})])

    result = await neo4j_backend.add_entity("EigenLayer", "protocol")

    assert result == "abc123"
    assert len(mock_driver.session_mock.queries) == 1
    query = mock_driver.session_mock.queries[0][0]
    assert "MERGE" in query
    assert "mention_count" in query


async def test_add_entity_strips_whitespace(neo4j_backend: Neo4jBackend) -> None:
    """add_entity normalizes entity name."""
    mock_driver: MockDriver = neo4j_backend._driver  # type: ignore[assignment]
    mock_driver.session_mock.set_response([MockRecord({"id": "xyz"})])

    await neo4j_backend.add_entity("  EigenLayer  ")

    kwargs = mock_driver.session_mock.queries[0][1]
    assert kwargs["name"] == "EigenLayer"


# ── add_edge ──────────────────────────────────────────────────────────────


async def test_add_edge_creates_relationship(neo4j_backend: Neo4jBackend) -> None:
    """add_edge creates a typed relationship with properties."""
    await neo4j_backend.add_edge(
        "id1", "id2", "PARTNERED_WITH",
        {"fact": "Google partnered with EigenLayer", "confidence": 0.9},
    )

    mock_driver: MockDriver = neo4j_backend._driver  # type: ignore[assignment]
    assert len(mock_driver.session_mock.queries) == 1
    query = mock_driver.session_mock.queries[0][0]
    assert "PARTNERED_WITH" in query
    assert "MATCH" in query
    assert "CREATE" in query


async def test_add_edge_sanitizes_rel_type(neo4j_backend: Neo4jBackend) -> None:
    """add_edge sanitizes relationship type for Cypher safety."""
    await neo4j_backend.add_edge("id1", "id2", "HAS-RELATION")

    mock_driver: MockDriver = neo4j_backend._driver  # type: ignore[assignment]
    query = mock_driver.session_mock.queries[0][0]
    # Hyphen should be replaced with underscore
    assert "HAS_RELATION" in query
    assert "HAS-RELATION" not in query


# ── traverse ──────────────────────────────────────────────────────────────


async def test_traverse_without_edge_filter(neo4j_backend: Neo4jBackend) -> None:
    """traverse generates correct Cypher without edge type filter."""
    mock_driver: MockDriver = neo4j_backend._driver  # type: ignore[assignment]
    mock_driver.session_mock.set_response([
        MockRecord({"id": "eid1"}),
        MockRecord({"id": "eid2"}),
    ])

    result = await neo4j_backend.traverse("EigenLayer", depth=2)

    assert result == ["eid1", "eid2"]
    query = mock_driver.session_mock.queries[0][0]
    assert "*1..2" in query
    assert "name: $name" in query


async def test_traverse_with_edge_filter(neo4j_backend: Neo4jBackend) -> None:
    """traverse filters by relationship types."""
    mock_driver: MockDriver = neo4j_backend._driver  # type: ignore[assignment]
    mock_driver.session_mock.set_response([MockRecord({"id": "eid1"})])

    result = await neo4j_backend.traverse(
        "EigenLayer", depth=1, edge_types=["PARTNERED_WITH", "INVESTED_IN"],
    )

    assert result == ["eid1"]
    query = mock_driver.session_mock.queries[0][0]
    assert "PARTNERED_WITH|INVESTED_IN" in query


# ── find_path ─────────────────────────────────────────────────────────────


async def test_find_path_returns_ids(neo4j_backend: Neo4jBackend) -> None:
    """find_path uses shortestPath and returns entity IDs."""
    mock_driver: MockDriver = neo4j_backend._driver  # type: ignore[assignment]
    mock_driver.session_mock.set_response([
        MockRecord({"entity_ids": ["id1", "id2", "id3"]}),
    ])

    result = await neo4j_backend.find_path("Google", "Ethereum")

    assert result == ["id1", "id2", "id3"]
    query = mock_driver.session_mock.queries[0][0]
    assert "shortestPath" in query


async def test_find_path_no_path(neo4j_backend: Neo4jBackend) -> None:
    """find_path returns empty list when no path exists."""
    result = await neo4j_backend.find_path("Isolated_A", "Isolated_B")
    assert result == []


# ── close ─────────────────────────────────────────────────────────────────


async def test_close_calls_driver_close(neo4j_backend: Neo4jBackend) -> None:
    """close() closes the Neo4j driver."""
    mock_driver: MockDriver = neo4j_backend._driver  # type: ignore[assignment]
    # Replace with AsyncMock to verify call
    original_close = mock_driver.close
    close_called = False

    async def track_close() -> None:
        nonlocal close_called
        close_called = True

    mock_driver.close = track_close  # type: ignore[assignment]
    await neo4j_backend.close()
    assert close_called
