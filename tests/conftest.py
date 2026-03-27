"""Shared test fixtures for tensory tests."""

from __future__ import annotations

import pytest

from tensory import Tensory


@pytest.fixture
async def store() -> Tensory:
    """Create an in-memory Tensory instance for testing."""
    s = await Tensory.create(":memory:")
    yield s  # type: ignore[misc]
    await s.close()
