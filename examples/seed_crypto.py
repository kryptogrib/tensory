"""Seed script — load crypto facts + entity relations into the dashboard database.

Usage:
    uv run python examples/seed_crypto.py              # seed data/tensory.db
    uv run python examples/seed_crypto.py :memory:     # test in-memory (prints stats)
"""

from __future__ import annotations

import asyncio
import sys

from tensory import Claim, ClaimType, Tensory
from tensory.models import EntityRelation, MemoryType

GREEN = "\033[92m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}\u2713{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {DIM}{msg}{RESET}")


# ── Crypto facts to seed ────────────────────────────────────────────────

CRYPTO_CLAIMS: list[dict[str, object]] = [
    # Bitcoin
    {
        "text": "Bitcoin reached an all-time high of $109,000 in January 2025",
        "entities": ["Bitcoin"],
        "type": ClaimType.FACT,
        "temporal": "2025-01-20",
        "confidence": 0.95,
    },
    {
        "text": "Bitcoin halving reduced block reward from 6.25 to 3.125 BTC in April 2024",
        "entities": ["Bitcoin"],
        "type": ClaimType.FACT,
        "temporal": "2024-04-19",
        "confidence": 1.0,
    },
    {
        "text": "Bitcoin dominance exceeds 60% of total crypto market cap in Q1 2025",
        "entities": ["Bitcoin"],
        "type": ClaimType.OBSERVATION,
        "temporal": "2025-03",
        "confidence": 0.85,
    },
    # Ethereum
    {
        "text": "Ethereum completed the Dencun upgrade enabling proto-danksharding (EIP-4844) in March 2024",
        "entities": ["Ethereum"],
        "type": ClaimType.FACT,
        "temporal": "2024-03-13",
        "confidence": 1.0,
    },
    {
        "text": "Ethereum Layer 2 rollups reduced transaction fees by over 90% after Dencun",
        "entities": ["Ethereum"],
        "type": ClaimType.OBSERVATION,
        "temporal": "2024-04",
        "confidence": 0.9,
    },
    {
        "text": "Ethereum staking ratio reached 28% of total ETH supply",
        "entities": ["Ethereum", "ETH"],
        "type": ClaimType.FACT,
        "temporal": "2025-01",
        "confidence": 0.88,
    },
    # Solana
    {
        "text": "Solana processed over 65 million transactions per day in Q4 2024",
        "entities": ["Solana"],
        "type": ClaimType.FACT,
        "temporal": "2024-12",
        "confidence": 0.85,
    },
    {
        "text": "Solana TVL surpassed $8 billion driven by DeFi and memecoin activity",
        "entities": ["Solana"],
        "type": ClaimType.FACT,
        "temporal": "2025-01",
        "confidence": 0.82,
    },
    # DeFi protocols
    {
        "text": "Lido Finance controls over 28% of all staked ETH making it the largest liquid staking provider",
        "entities": ["Lido Finance", "ETH"],
        "type": ClaimType.FACT,
        "temporal": "2025-02",
        "confidence": 0.9,
    },
    {
        "text": "Aave V3 deployed on 12 chains with total deposits exceeding $20 billion",
        "entities": ["Aave"],
        "type": ClaimType.FACT,
        "temporal": "2025-01",
        "confidence": 0.87,
    },
    {
        "text": "Uniswap V4 launched with hooks architecture enabling customizable pool logic",
        "entities": ["Uniswap"],
        "type": ClaimType.FACT,
        "temporal": "2025-01",
        "confidence": 0.92,
    },
    {
        "text": "EigenLayer restaking protocol accumulated over $15 billion in TVL",
        "entities": ["EigenLayer"],
        "type": ClaimType.FACT,
        "temporal": "2024-06",
        "confidence": 0.88,
    },
    # Regulatory
    {
        "text": "SEC approved 11 spot Bitcoin ETFs in January 2024",
        "entities": ["SEC", "Bitcoin"],
        "type": ClaimType.FACT,
        "temporal": "2024-01-10",
        "confidence": 1.0,
    },
    {
        "text": "BlackRock iShares Bitcoin Trust (IBIT) became the fastest ETF to reach $50 billion AUM",
        "entities": ["BlackRock", "Bitcoin"],
        "type": ClaimType.FACT,
        "temporal": "2025-02",
        "confidence": 0.93,
    },
    {
        "text": "EU Markets in Crypto-Assets (MiCA) regulation went into full effect in December 2024",
        "entities": ["EU", "MiCA"],
        "type": ClaimType.FACT,
        "temporal": "2024-12-30",
        "confidence": 1.0,
    },
    # Stablecoins
    {
        "text": "USDT market cap exceeded $140 billion maintaining dominance in stablecoin market",
        "entities": ["USDT", "Tether"],
        "type": ClaimType.FACT,
        "temporal": "2025-03",
        "confidence": 0.9,
    },
    {
        "text": "USDC regained market share after Circle achieved regulatory clarity with MiCA compliance",
        "entities": ["USDC", "Circle", "MiCA"],
        "type": ClaimType.OBSERVATION,
        "temporal": "2025-01",
        "confidence": 0.8,
    },
    # Partnerships & tech
    {
        "text": "Google Cloud partnered with EigenLayer to provide infrastructure for restaking validators",
        "entities": ["Google Cloud", "EigenLayer"],
        "type": ClaimType.FACT,
        "temporal": "2025-03",
        "confidence": 0.85,
    },
    {
        "text": "Chainlink CCIP became the dominant cross-chain interoperability standard adopted by major DeFi protocols",
        "entities": ["Chainlink", "CCIP"],
        "type": ClaimType.OBSERVATION,
        "temporal": "2025-02",
        "confidence": 0.83,
    },
    # Procedural — how-to knowledge
    {
        "text": "To stake ETH on Lido: connect wallet to lido.fi, enter amount, approve transaction, receive stETH token",
        "entities": ["Lido Finance", "ETH"],
        "type": ClaimType.FACT,
        "memory_type": MemoryType.PROCEDURAL,
        "trigger": "user wants to stake ETH via liquid staking",
        "steps": [
            "Connect wallet to lido.fi",
            "Enter ETH amount to stake",
            "Approve the staking transaction",
            "Receive stETH 1:1 for staked ETH",
        ],
        "termination_condition": "stETH appears in wallet balance",
        "confidence": 0.95,
    },
]

# ── Entity relations (graph edges) ──────────────────────────────────────

CRYPTO_RELATIONS: list[EntityRelation] = [
    # Bitcoin ecosystem
    EntityRelation(
        from_entity="SEC",
        to_entity="Bitcoin",
        rel_type="APPROVED_ETF_FOR",
        fact="SEC approved 11 spot Bitcoin ETFs in January 2024",
        confidence=1.0,
    ),
    EntityRelation(
        from_entity="BlackRock",
        to_entity="Bitcoin",
        rel_type="LAUNCHED_ETF_FOR",
        fact="BlackRock iShares Bitcoin Trust (IBIT) became the fastest ETF to reach $50B AUM",
        confidence=0.93,
    ),
    # Ethereum ecosystem
    EntityRelation(
        from_entity="Lido Finance",
        to_entity="ETH",
        rel_type="PROVIDES_STAKING_FOR",
        fact="Lido Finance controls over 28% of all staked ETH",
        confidence=0.9,
    ),
    EntityRelation(
        from_entity="Ethereum",
        to_entity="ETH",
        rel_type="NATIVE_TOKEN",
        fact="ETH is the native token of the Ethereum network",
        confidence=1.0,
    ),
    # DeFi protocols
    EntityRelation(
        from_entity="Google Cloud",
        to_entity="EigenLayer",
        rel_type="PARTNERED_WITH",
        fact="Google Cloud partnered with EigenLayer for restaking validator infrastructure",
        confidence=0.85,
    ),
    EntityRelation(
        from_entity="EigenLayer",
        to_entity="Ethereum",
        rel_type="BUILT_ON",
        fact="EigenLayer restaking protocol is built on Ethereum",
        confidence=0.95,
    ),
    EntityRelation(
        from_entity="Aave",
        to_entity="Ethereum",
        rel_type="DEPLOYED_ON",
        fact="Aave V3 deployed on Ethereum and 11 other chains",
        confidence=0.87,
    ),
    EntityRelation(
        from_entity="Uniswap",
        to_entity="Ethereum",
        rel_type="DEPLOYED_ON",
        fact="Uniswap V4 launched on Ethereum with hooks architecture",
        confidence=0.92,
    ),
    EntityRelation(
        from_entity="Chainlink",
        to_entity="CCIP",
        rel_type="DEVELOPED",
        fact="Chainlink developed CCIP as cross-chain interoperability protocol",
        confidence=0.9,
    ),
    # Stablecoins
    EntityRelation(
        from_entity="Tether",
        to_entity="USDT",
        rel_type="ISSUES",
        fact="Tether issues and manages the USDT stablecoin",
        confidence=1.0,
    ),
    EntityRelation(
        from_entity="Circle",
        to_entity="USDC",
        rel_type="ISSUES",
        fact="Circle issues and manages the USDC stablecoin",
        confidence=1.0,
    ),
    EntityRelation(
        from_entity="Circle",
        to_entity="MiCA",
        rel_type="COMPLIANT_WITH",
        fact="Circle achieved MiCA regulatory compliance for USDC in EU",
        confidence=0.8,
    ),
    EntityRelation(
        from_entity="EU",
        to_entity="MiCA",
        rel_type="ENACTED",
        fact="EU enacted Markets in Crypto-Assets regulation in December 2024",
        confidence=1.0,
    ),
    # Solana
    EntityRelation(
        from_entity="Solana",
        to_entity="Ethereum",
        rel_type="COMPETES_WITH",
        fact="Solana competes with Ethereum as high-throughput L1 blockchain",
        confidence=0.8,
    ),
]


async def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/tensory.db"

    print(f"\n{BOLD}{CYAN}{'=' * 55}{RESET}")
    print(f"{BOLD}{CYAN}  Tensory Crypto Seed \u2192 {db_path}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 55}{RESET}\n")

    store = await Tensory.create(db_path)

    # Create a research context
    ctx = await store.create_context(
        goal="Track cryptocurrency market developments, DeFi protocols, and regulatory changes",
        domain="crypto",
    )
    ok(f"Context created: {ctx.id[:12]}...")
    info(f"  goal: {ctx.goal}")

    # Build Claim objects
    claims: list[Claim] = []
    for data in CRYPTO_CLAIMS:
        kwargs: dict[str, object] = {
            "text": str(data["text"]),
            "entities": list(data.get("entities", [])),  # type: ignore[arg-type]
            "type": data.get("type", ClaimType.FACT),
            "confidence": float(data.get("confidence", 1.0)),
        }
        if "temporal" in data:
            kwargs["temporal"] = str(data["temporal"])
        if "memory_type" in data:
            kwargs["memory_type"] = data["memory_type"]
        if "trigger" in data:
            kwargs["trigger"] = str(data["trigger"])
        if "steps" in data:
            kwargs["steps"] = list(data["steps"])  # type: ignore[arg-type]
        if "termination_condition" in data:
            kwargs["termination_condition"] = str(data["termination_condition"])

        claims.append(Claim(**kwargs))  # type: ignore[arg-type]

    # Ingest claims
    result = await store.add_claims(claims, context_id=ctx.id)

    print()
    ok(f"Added {len(result.claims)} claims")

    if result.collisions:
        ok(f"Detected {len(result.collisions)} collisions")
    if result.new_entities:
        ok(f"New entities: {', '.join(result.new_entities[:10])}")

    # Ingest relations (graph edges)
    edge_count = 0
    for rel in CRYPTO_RELATIONS:
        from_id = await store.graph.add_entity(rel.from_entity)
        to_id = await store.graph.add_entity(rel.to_entity)
        await store.graph.add_edge(
            from_id,
            to_id,
            rel.rel_type,
            {"fact": rel.fact, "confidence": rel.confidence},
        )
        edge_count += 1
    await store.db.commit()
    ok(f"Added {edge_count} entity relations (graph edges)")

    # Stats
    stats = await store.stats()
    print()
    ok(f"Total claims: {stats['counts']['claims']}")
    ok(f"Total entities: {stats['counts']['entities']}")
    ok(f"Avg salience: {stats['avg_salience']:.2f}")
    ok(f"By type: {stats['claims_by_type']}")

    await store.close()
    print(f"\n{GREEN}{BOLD}  Done! Start the dashboard: make dashboard{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
