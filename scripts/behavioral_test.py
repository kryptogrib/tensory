"""Behavioral test: inject known facts → recall → check if they surface.

Injects 3 claims of different types, then runs recall queries
to see if they are found. This tests the full pipeline:
add_claims → embeddings → search → format_context.

Usage:
    uv run python scripts/behavioral_test.py [--db PATH]
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Test claims — distinctive enough to not collide with existing data
TEST_CLAIMS = [
    {
        "text": "The secret passphrase for the tensory vault is 'orange-cat-42'",
        "type": "fact",
        "entities": ["tensory vault"],
    },
    {
        "text": "When deploying tensory to production, always run migrate() before opening connections because schema v3 adds collision_log table",
        "type": "experience",
        "entities": ["tensory", "collision_log"],
    },
    {
        "text": "Redis is preferred over Memcached for tensory caching because it supports sorted sets for temporal queries",
        "type": "opinion",
        "entities": ["Redis", "Memcached", "tensory"],
    },
]

# Queries that should surface the injected claims
TEST_QUERIES = [
    ("tensory vault passphrase", "orange-cat-42"),
    ("how to deploy tensory production", "migrate()"),
    ("caching tensory redis", "sorted sets"),
    # Cross-domain query — should NOT surface test claims
    ("ethereum gas fees", None),
]


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="~/.local/share/tensory/memory.db")
    parser.add_argument("--cleanup", action="store_true", help="Remove test claims after")
    args = parser.parse_args()

    db_path = os.path.expanduser(args.db)

    # Create embedder if available
    embedder = None
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        from tensory.embedder import OpenAIEmbedder

        embedder = OpenAIEmbedder(api_key=api_key)
        print("  Embedder: OpenAIEmbedder ✅")
    else:
        print("  Embedder: NullEmbedder (no OPENAI_API_KEY)")

    from tensory import Claim, Tensory

    store = await Tensory.create(db_path, embedder=embedder)

    try:
        # Step 1: Inject test claims
        print(f"\n{'='*60}")
        print("  STEP 1: Injecting 3 test claims")
        print(f"{'='*60}\n")

        test_claim_ids: list[str] = []
        claims = [
            Claim(
                text=c["text"],
                type=c["type"],  # type: ignore[arg-type]
                entities=c["entities"],
            )
            for c in TEST_CLAIMS
        ]
        result = await store.add_claims(claims)
        for claim in result.claims:
            test_claim_ids.append(claim.id)
            print(f"  ✅ [{claim.type}] {claim.text[:70]}...")

        # Step 2: Search for each query
        print(f"\n{'='*60}")
        print("  STEP 2: Testing recall queries")
        print(f"{'='*60}\n")

        all_passed = True
        for query, expected_fragment in TEST_QUERIES:
            results = await store.search(query, limit=5)
            result_texts = [r.claim.text for r in results]
            joined = " ".join(result_texts).lower()

            if expected_fragment is None:
                # Negative test — should NOT find test claims
                found_test = any(
                    tc["text"][:30].lower() in joined
                    for tc in TEST_CLAIMS
                )
                status = "✅ PASS" if not found_test else "⚠️  FALSE POSITIVE"
                if found_test:
                    all_passed = False
                print(f"  {status} | Query: \"{query}\"")
                print(f"         Expected: no test claims")
                if results:
                    print(f"         Got: {results[0].claim.text[:60]}...")
            else:
                found = expected_fragment.lower() in joined
                status = "✅ PASS" if found else "❌ FAIL"
                if not found:
                    all_passed = False
                print(f"  {status} | Query: \"{query}\"")
                print(f"         Expected fragment: \"{expected_fragment}\"")
                if results:
                    print(f"         Top result: {results[0].claim.text[:70]}...")
                    print(f"         Score: {results[0].score:.2f}")
                else:
                    print(f"         Got: no results")
            print()

        # Step 3: Summary
        print(f"{'='*60}")
        if all_passed:
            print("  🎉 ALL TESTS PASSED — recall pipeline works!")
        else:
            print("  ⚠️  SOME TESTS FAILED — check search quality")
        print(f"{'='*60}\n")

        # Cleanup
        if args.cleanup:
            print("  Cleaning up test claims...")
            async with store.db.execute("BEGIN"):
                for cid in test_claim_ids:
                    await store.db.execute("DELETE FROM claim_entities WHERE claim_id = ?", (cid,))
                    await store.db.execute("DELETE FROM claims WHERE id = ?", (cid,))
                await store.db.execute("COMMIT")
            print(f"  Removed {len(test_claim_ids)} test claims")

    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
