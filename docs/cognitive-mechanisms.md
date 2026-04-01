# Cognitive Mechanisms

All mechanisms below are algorithmic, zero LLM calls. They run as pure computation against the stored claim graph.

## Mechanisms

| Mechanism | What it does |
|---|---|
| **Salience + decay** | Claims fade over time (exponential, per-type rates) |
| **Surprise score** | Novel claims get salience boost |
| **Priming** | Recently-searched entities boost related results |
| **Reinforce on access** | Searched claims get stronger (+0.05 salience) |
| **Waypoints** | Auto-link similar claims (cosine >= 0.75) |
| **Structural collision** | Same entity + different value = auto-conflict |
| **Consolidation** | Cluster claims into OBSERVATION summaries |
| **Source fingerprinting** | Per-source reliability profiles |
| **Sentiment tagging** | Keyword-based sentiment + urgency detection |

## Collision Detection

Two-level system, zero LLM:

1. **Structural** — same entities + overlapping temporal validity
2. **Semantic** — weighted composite: vector (40%) + entity overlap (25%) + temporal proximity (20%) + waypoint link (15%)

Salience updates on collision:
- `contradiction` — salience x 0.5
- `supersedes` — salience x 0.1
- `confirms` — salience + 0.2
- `related` — salience + 0.05
