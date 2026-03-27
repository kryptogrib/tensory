"""Tests for graph.py — SQLiteGraphBackend."""

from __future__ import annotations

from tensory import Tensory


async def test_find_path_between_entities(store: Tensory) -> None:
    """find_path returns shortest path through entity_relations."""
    eid_a = await store._graph.add_entity("Google", "company")
    eid_b = await store._graph.add_entity("EigenLayer", "protocol")
    eid_c = await store._graph.add_entity("Ethereum", "blockchain")

    await store._graph.add_edge(eid_a, eid_b, "PARTNERED_WITH")
    await store._graph.add_edge(eid_b, eid_c, "BUILT_ON")
    await store._db.commit()

    path = await store._graph.find_path("Google", "Ethereum")
    assert len(path) == 3  # Google → EigenLayer → Ethereum
    assert eid_a in path
    assert eid_c in path


async def test_find_path_returns_empty_for_disconnected(store: Tensory) -> None:
    """find_path returns [] when no path exists."""
    await store._graph.add_entity("Isolated_A")
    await store._graph.add_entity("Isolated_B")
    await store._db.commit()

    path = await store._graph.find_path("Isolated_A", "Isolated_B")
    assert path == []


async def test_traverse_with_depth_limit(store: Tensory) -> None:
    """Traversal respects depth limit."""
    eid_a = await store._graph.add_entity("A")
    eid_b = await store._graph.add_entity("B")
    eid_c = await store._graph.add_entity("C")

    await store._graph.add_edge(eid_a, eid_b, "LINKED")
    await store._graph.add_edge(eid_b, eid_c, "LINKED")
    await store._db.commit()

    # Depth 1: A → B only
    depth1 = await store._graph.traverse("A", depth=1)
    assert eid_b in depth1
    # C should NOT be reachable at depth 1
    assert eid_c not in depth1

    # Depth 2: A → B → C
    depth2 = await store._graph.traverse("A", depth=2)
    assert eid_b in depth2
    assert eid_c in depth2


async def test_traverse_with_edge_type_filter(store: Tensory) -> None:
    """Traversal can filter by edge type."""
    eid_a = await store._graph.add_entity("X")
    eid_b = await store._graph.add_entity("Y")
    eid_c = await store._graph.add_entity("Z")

    await store._graph.add_edge(eid_a, eid_b, "PARTNERED_WITH")
    await store._graph.add_edge(eid_a, eid_c, "COMPETED_WITH")
    await store._db.commit()

    # Filter to only PARTNERED_WITH
    partners = await store._graph.traverse("X", depth=1, edge_types=["PARTNERED_WITH"])
    assert eid_b in partners
    assert eid_c not in partners
