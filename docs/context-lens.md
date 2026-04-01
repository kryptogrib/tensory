# Context as Lens

The core innovation in Tensory: a **Context** defines *why* you're reading text, not just what text you're reading. The same episode can yield completely different claims depending on the context applied to it.

This means a single piece of information -- a news article, a conversation transcript, a document -- is not locked into one interpretation. By switching the context, Tensory re-extracts knowledge through a different analytical lens.

## How it works

A `Context` carries a goal that steers claim extraction. When an episode is added under one context, the extraction pipeline surfaces claims relevant to that goal. Calling `reevaluate()` on the same episode with a different context produces an entirely new set of claims -- without re-ingesting the source text.

```python
# Same news article...
crypto_ctx = await store.create_context(goal="Track DeFi protocols")
tech_ctx = await store.create_context(goal="Track Big Tech AI strategy")

result = await store.add("Google partners with EigenLayer...", context=crypto_ctx)
# → Claims about EigenLayer, restaking, DeFi partnerships

new_claims = await store.reevaluate(result.episode_id, context=tech_ctx)
# → Claims about Google's cloud strategy, AI infrastructure moves
```

One episode, two contexts, two completely different sets of extracted knowledge. The context acts as a lens that determines what is worth remembering.
