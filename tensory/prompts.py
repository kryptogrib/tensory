"""LLM prompts for tensory — extraction and CARA reflection.

Sources:
- Extraction: adapted from Hindsight A.1 (TEMPR fact extraction) + tensory plan
- CARA Opinion Formation: Hindsight Appendix A.2 (verbatim, adapted)
- Observation Synthesis: Hindsight Appendix A.3 (verbatim, adapted)

Reference: arxiv.org/abs/2512.12818 (Hindsight paper)
"""

from __future__ import annotations

from typing import Final

# ── 1. Context-aware extraction (used by extract.py) ─────────────────────

EXTRACT_WITH_CONTEXT: Final[
    str
] = """You are extracting information for a specific research goal.

RESEARCH GOAL: {goal}
DOMAIN: {domain}

Extract claims from this text that are RELEVANT to the research goal above.
Skip information that is not relevant to the goal.

VERBATIM PRESERVATION — these rules override all others:
- NEVER paraphrase proper nouns, specific objects, locations, or quantities
- Use the speaker's EXACT words for: country names, city names, people's names, numbers, colors, specific objects
- If the text says "Sweden", write "Sweden" — NOT "home country" or "Scandinavian country"
- If the text says "sunset", write "sunset" — NOT "nature-inspired" or "landscape"
- If the text says "3 children", write "3 children" — NOT "kids" or "younger children"
- If the text says "rainbow flag", write "rainbow flag" — NOT "symbol" or "flag"
- When in doubt, QUOTE the original words rather than summarize

WRONG: "Melanie painted a nature-inspired artwork"
RIGHT: "Melanie painted a sunset"

WRONG: "Caroline moved from her home country"
RIGHT: "Caroline moved from Sweden"

IMPORTANT temporal rules:
- If the text has a date header (e.g. "[Session 3 — 2:00 pm on 25 May, 2023]"), use it as the reference date
- Convert ALL relative time references ("last Saturday", "yesterday", "next month") to absolute dates using the reference date
- Include the specific date IN the claim text itself, e.g. "On 20 May 2023, Melanie ran a charity race"
- The "temporal" field should contain the exact date in YYYY-MM-DD format when possible

ENTITY RULES:
- Entities are PROPER NOUNS: people, companies, projects, protocols, tools, places, specific products.
- Use consistent Title Case: "EigenLayer", "Bitcoin", "Claude Code" — not "eigenlayer" or "claude code".
- NEVER use generic terms as entities: "claims", "database", "extraction", "plugin", "API", "LLM".
- Good: ["Tensory", "SQLite", "EigenLayer"]  Bad: ["claims", "extraction", "plugin"]

For each claim, also:
- Rate its relevance to the research goal (0.0-1.0)
- Identify entity relationships (who did what to whom)

TEXT:
{text}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "claims": [
    {{
      "text": "atomic claim WITH dates included in the text",
      "type": "fact|experience|observation|opinion",
      "entities": ["Entity1", "Entity2"],
      "temporal": "YYYY-MM-DD or descriptive date, never null if any time reference exists",
      "confidence": 0.0-1.0,
      "relevance": 0.0-1.0
    }}
  ],
  "relations": [
    {{
      "from": "Entity1",
      "to": "Entity2",
      "type": "PARTNERED_WITH|INVESTED_IN|DEPARTED_FROM|...",
      "fact": "human readable description"
    }}
  ]
}}

If nothing is relevant to the research goal, return {{"claims": [], "relations": []}}"""

EXTRACT_GENERIC: Final[
    str
] = """Extract all factual claims and entity relationships from this text.

VERBATIM PRESERVATION — these rules override all others:
- NEVER paraphrase proper nouns, specific objects, locations, or quantities
- Use the speaker's EXACT words for: country names, city names, people's names, numbers, colors, specific objects
- If the text says "Sweden", write "Sweden" — NOT "home country" or "Scandinavian country"
- If the text says "sunset", write "sunset" — NOT "nature-inspired" or "landscape"
- If the text says "3 children", write "3 children" — NOT "kids" or "younger children"
- If the text says "rainbow flag", write "rainbow flag" — NOT "symbol" or "flag"
- When in doubt, QUOTE the original words rather than summarize

WRONG: "Melanie painted a nature-inspired artwork"
RIGHT: "Melanie painted a sunset"

WRONG: "Caroline moved from her home country"
RIGHT: "Caroline moved from Sweden"

IMPORTANT temporal rules:
- If the text has a date header (e.g. "[Session 3 — 2:00 pm on 25 May, 2023]"), use it as the reference date
- Convert ALL relative time references ("last Saturday", "yesterday", "next month") to absolute dates using the reference date
- Include the specific date IN the claim text itself, e.g. "On 20 May 2023, Melanie ran a charity race"
- The "temporal" field should contain the exact date in YYYY-MM-DD format when possible

ENTITY RULES:
- Entities are PROPER NOUNS: people, companies, projects, protocols, tools, places, specific products.
- Use consistent Title Case: "EigenLayer", "Bitcoin", "Claude Code" — not "eigenlayer" or "claude code".
- NEVER use generic terms as entities: "claims", "database", "extraction", "plugin", "API", "LLM".
- Good: ["Tensory", "SQLite", "EigenLayer"]  Bad: ["claims", "extraction", "plugin"]

TEXT:
{text}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "claims": [
    {{
      "text": "atomic claim WITH dates included in the text",
      "type": "fact|experience|observation|opinion",
      "entities": ["Entity1", "Entity2"],
      "temporal": "YYYY-MM-DD or descriptive date, never null if any time reference exists",
      "confidence": 0.0-1.0,
      "relevance": 1.0
    }}
  ],
  "relations": [
    {{
      "from": "Entity1",
      "to": "Entity2",
      "type": "PARTNERED_WITH|INVESTED_IN|DEPARTED_FROM|...",
      "fact": "human readable description"
    }}
  ]
}}

If no claims can be extracted, return {{"claims": [], "relations": []}}"""

# ── 2. CARA Opinion Formation (used by reflect()) ────────────────────────

CARA_OPINION_FORMATION: Final[
    str
] = """Extract any NEW opinions or perspectives from the recalled facts below and rewrite them in FIRST-PERSON as if YOU are stating the opinion directly.

QUERY: {query}
DISPOSITION: {disposition}

RECALLED FACTS:
{facts_text}

COLLISIONS DETECTED:
{collisions_text}

Your task: Analyze the facts and collisions, then form opinions considering the disposition above.
An opinion is a judgment, viewpoint, or conclusion that goes beyond just stating facts.

IMPORTANT: Do NOT extract statements like:
- "I don't have enough information"
- "The facts don't contain information about X"

ONLY extract actual opinions about substantive topics.

CRITICAL FORMAT REQUIREMENTS:
1) ALWAYS start with first-person phrases: "I think...", "I believe...", "In my view...", "Previously I thought... but now..."
2) NEVER use third-person
3) Include the reasoning naturally within the statement
4) Provide a confidence score (0.0 to 1.0)
5) List entities mentioned in each opinion

Return ONLY valid JSON:
{{
  "opinions": [
    {{
      "text": "I believe that ... because ...",
      "confidence": 0.75,
      "entities": ["Entity1"]
    }}
  ]
}}

If no meaningful opinions can be formed, return {{"opinions": []}}"""

# ── 3. Observation Synthesis (used by reflect()) ─────────────────────────

OBSERVATION_SYNTHESIS: Final[
    str
] = """You are an objective observer synthesizing facts about an entity. Generate clear, factual observations without opinions or behavioral profile influence. Be concise and accurate.

Based on the following facts about "{entity_name}", generate a list of key observations.

FACTS:
{facts_text}

GUIDELINES:
1. Each observation should be a factual statement about {entity_name}
2. Combine related facts into single observations where appropriate
3. Be objective — do not add opinions, judgments, or interpretations
4. Focus on what we KNOW about {entity_name}
5. Write in third person
6. If there are conflicting facts, note the most recent or most supported one

Generate 3-7 observations. If very few facts — generate fewer.

Return ONLY valid JSON:
{{
  "observations": [
    {{
      "text": "factual observation about {entity_name}",
      "entities": ["{entity_name}", "other entities mentioned"]
    }}
  ]
}}"""

# ── 4. Procedural Memory — skill induction (PlugMem + ProcMEM) ────────

PROCEDURAL_INDUCTION_PROMPT: Final[
    str
] = """Extract procedural knowledge (skills) from this experience.

A skill is a reusable procedure: "how to do something" — not just "what happened".
Use the Skill-MDP framework:
- trigger: when this skill should activate (activation condition)
- steps: ordered list of concrete, executable actions
- termination_condition: when the skill is complete
- expected_outcome: what success looks like

TEXT:
{text}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "skills": [
    {{
      "trigger": "condition that activates this skill",
      "steps": ["step 1", "step 2", "step 3"],
      "termination_condition": "condition that signals completion",
      "expected_outcome": "what the result should be",
      "entities": ["Entity1", "Entity2"]
    }}
  ]
}}

If no procedural knowledge found, return {{"skills": []}}"""

# ── 5. Skill Update — feedback-driven evolution (ProcMEM + LangMem) ───

SKILL_UPDATE_PROMPT: Final[str] = """Evaluate the outcome of applying a skill and suggest updates.

SKILL:
{skill_text}

OUTCOME (success={success}, feedback={outcome}):

Analyze:
1. Should steps be updated? (add/remove/reorder)
2. Should trigger be refined?
3. Should the skill be deprecated (consistent failures)?

Return ONLY valid JSON:
{{
  "updated_steps": ["step1", "step2"],
  "updated_trigger": "refined trigger or null",
  "updated_termination": "refined condition or null",
  "should_deprecate": false,
  "reasoning": "why these changes"
}}"""

# ── 6. Topic Segmentation — splitting long texts for hybrid extraction ──

TOPIC_SEGMENTATION_PROMPT: Final[
    str
] = """Split this text into thematic sections for detailed analysis.

Rules:
- Create NO MORE than {max_segments} sections
- Each section should be a self-contained topic or event
- Preserve ALL text — do not summarize or skip content
- If the text is already focused on one topic, return 1 section

TEXT:
{text}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "sections": [
    {{
      "title": "short descriptive title",
      "text": "full text of this section (copy verbatim, do not summarize)"
    }}
  ]
}}"""
