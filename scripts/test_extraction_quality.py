"""Test extraction quality: compare old vs new prompt on real data.

Runs the new EXTRACT_GENERIC prompt against sample texts from different domains
and prints the extracted claims for manual inspection.

Usage:
    uv run python scripts/test_extraction_quality.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tensory.prompts import EXTRACT_GENERIC

# Sample texts from different domains
SAMPLES = {
    "code_session": """
We debugged the dashboard not showing claims. The issue was that the plugin writes
to ~/.local/share/tensory/memory.db using TENSORY_DB env var, but the API server
reads from data/tensory.db using TENSORY_DB_PATH env var. Two different env var names
pointing to different databases. We fixed it by making the API check TENSORY_DB first,
then fall back to TENSORY_DB_PATH. Also added os.path.expanduser() because Python
doesn't expand tilde automatically. 322 tests passed after the fix. The Docker
container was restarted with -e TENSORY_DB_PATH=/data/memory.db flag.
""",
    "crypto_news": """
Ethereum's Pectra upgrade went live on March 15, 2025, introducing EIP-7702 which
allows EOAs to temporarily act as smart contracts during a transaction. This changes
the account abstraction landscape significantly — wallets like MetaMask can now batch
transactions without deploying a separate contract. Gas costs for token approvals
dropped roughly 40%. Meanwhile, Solana's Firedancer validator client from Jump Crypto
reached mainnet beta with 200k TPS in testing. SOL traded at $187 after the news.
Vitalik published a blog post arguing that L2s should adopt based rollups to reduce
sequencer centralization risk.
""",
    "science_paper": """
A new paper from DeepMind, "Scaling LLM Test-Time Compute" (March 2025), shows that
spending more compute at inference time via chain-of-thought and self-verification
can match the performance of models 10x larger. They tested on GSM8K, MATH, and
ARC-Challenge. Key finding: a 7B parameter model with 32x test-time compute budget
matched a 70B model's accuracy. The paper ran 847 experiments across 3 months.
Implications: smaller models may be more cost-effective for reasoning tasks if
inference cost is acceptable. This aligns with the "inference scaling laws" hypothesis
from the Snell et al. (2024) paper. The authors note this doesn't work well for
pure knowledge retrieval tasks where the information simply isn't in the weights.
""",
}


async def main() -> None:
    # Try to get LLM from env
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("TENSORY_MODEL", "claude-haiku-4-5-20251001")

    if not base_url and not api_key:
        print("No LLM configured (need ANTHROPIC_BASE_URL or ANTHROPIC_API_KEY)")
        print("\nShowing prompt that would be sent:\n")
        print(EXTRACT_GENERIC.format(text=SAMPLES["code_session"][:200] + "..."))
        return

    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key or None, base_url=base_url or None)

    async def llm(prompt: str) -> str:
        resp = await client.messages.create(
            model=model, max_tokens=4096, messages=[{"role": "user", "content": prompt}]
        )
        return resp.content[0].text if resp.content else ""

    for domain, text in SAMPLES.items():
        print(f"\n{'='*60}")
        print(f"  DOMAIN: {domain}")
        print(f"{'='*60}")

        prompt = EXTRACT_GENERIC.format(text=text)
        raw = await llm(prompt)

        # Parse JSON
        try:
            # Strip markdown fences if present
            clean = raw.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            data = json.loads(clean)
        except json.JSONDecodeError:
            print(f"  Failed to parse: {raw[:200]}")
            continue

        claims = data.get("claims", [])
        relations = data.get("relations", [])

        print(f"  Claims extracted: {len(claims)}")
        print(f"  Relations: {len(relations)}")
        print()

        for i, c in enumerate(claims, 1):
            dur = c.get("durability", "?")
            typ = c.get("type", "?")
            conf = c.get("confidence", "?")
            marker = "🟢" if dur == "permanent" else "🟡" if dur == "long-term" else "🔴"
            print(f"  {marker} [{typ}, {dur}, conf={conf}]")
            print(f"     {c['text']}")
            print()

        if relations:
            print("  Relations:")
            for r in relations:
                print(f"    {r['from']} --[{r['type']}]--> {r['to']}: {r.get('fact', '')}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
