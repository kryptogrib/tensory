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


async def test_list_entities(store: Tensory) -> None:
    """list_entities returns entities ordered by mention_count desc."""
    # Add entities with different mention counts
    await store._graph.add_entity("Alpha", "org")
    await store._graph.add_entity("Beta", "person")
    # Mention Alpha again to bump count
    await store._graph.add_entity("Alpha", "org")
    await store._graph.add_entity("Alpha", "org")
    await store._db.commit()

    entities = await store._graph.list_entities()
    assert len(entities) == 2
    # Alpha mentioned 3 times, Beta 1 time
    assert entities[0]["name"] == "Alpha"
    assert entities[0]["mention_count"] == 3
    assert entities[1]["name"] == "Beta"
    assert entities[1]["mention_count"] == 1
    # Verify all expected fields present
    for ent in entities:
        assert "id" in ent
        assert "name" in ent
        assert "type" in ent
        assert "mention_count" in ent
        assert "first_seen" in ent


async def test_list_entities_min_mentions_filter(store: Tensory) -> None:
    """list_entities filters by min_mentions."""
    await store._graph.add_entity("Popular", "org")
    await store._graph.add_entity("Popular", "org")
    await store._graph.add_entity("Popular", "org")
    await store._graph.add_entity("Obscure", "org")
    await store._db.commit()

    # Only entities with >= 2 mentions
    entities = await store._graph.list_entities(min_mentions=2)
    assert len(entities) == 1
    assert entities[0]["name"] == "Popular"


async def test_list_edges(store: Tensory) -> None:
    """list_edges returns active edges with expected fields."""
    eid_a = await store._graph.add_entity("Foo", "org")
    eid_b = await store._graph.add_entity("Bar", "org")
    await store._graph.add_edge(
        eid_a,
        eid_b,
        "WORKS_WITH",
        properties={"fact": "Foo works with Bar", "episode_id": "ep1", "confidence": 0.95},
    )
    await store._db.commit()

    edges = await store._graph.list_edges()
    assert len(edges) == 1
    edge = edges[0]
    assert edge["from_entity"] == "Foo"
    assert edge["to_entity"] == "Bar"
    assert edge["rel_type"] == "WORKS_WITH"
    assert edge["fact"] == "Foo works with Bar"
    assert edge["confidence"] == 0.95
    # Verify all expected fields
    for field in (
        "id",
        "from_entity",
        "to_entity",
        "rel_type",
        "fact",
        "episode_id",
        "confidence",
        "created_at",
        "expired_at",
    ):
        assert field in edge


async def test_list_edges_entity_filter(store: Tensory) -> None:
    """list_edges filters by entity name."""
    eid_a = await store._graph.add_entity("Node1", "org")
    eid_b = await store._graph.add_entity("Node2", "org")
    eid_c = await store._graph.add_entity("Node3", "org")
    await store._graph.add_edge(eid_a, eid_b, "LINKED")
    await store._graph.add_edge(eid_b, eid_c, "LINKED")
    await store._db.commit()

    # Filter to edges involving Node1 only (by name, not ID)
    edges = await store._graph.list_edges(entity_filter="Node1")
    assert len(edges) == 1
    assert edges[0]["from_entity"] == "Node1"
    assert edges[0]["to_entity"] == "Node2"


async def test_subgraph(store: Tensory) -> None:
    """subgraph returns connected nodes and edges."""
    eid_a = await store._graph.add_entity("Center", "org")
    eid_b = await store._graph.add_entity("Neighbor1", "org")
    eid_c = await store._graph.add_entity("Neighbor2", "org")
    eid_d = await store._graph.add_entity("Distant", "org")
    await store._graph.add_edge(eid_a, eid_b, "KNOWS")
    await store._graph.add_edge(eid_a, eid_c, "KNOWS")
    await store._graph.add_edge(eid_c, eid_d, "KNOWS")
    await store._db.commit()

    result = await store._graph.subgraph("Center", depth=1)
    assert "nodes" in result
    assert "edges" in result

    node_names = {n["name"] for n in result["nodes"]}
    assert "Neighbor1" in node_names
    assert "Neighbor2" in node_names
    # Distant is depth=2, should NOT appear at depth=1
    assert "Distant" not in node_names

    # Edges should only be between reachable nodes
    assert len(result["edges"]) == 2
