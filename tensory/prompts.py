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
] = """You are building a long-term knowledge base focused on a specific research goal.

RESEARCH GOAL: {goal}
DOMAIN: {domain}

Extract ALL claims that are RELEVANT to the research goal and would be valuable when recalled weeks or months from now by someone with no memory of this conversation.

The test for every claim: "Would recalling this change how I think or act on this research goal?"
- YES → extract it. Causality, corrections, relationships, exact facts, specifics.
- NO → skip it. Narration, minor status updates, process logs, obvious context, trivial tasks, routine activities, filler, conversational pleasantries, vague statements.

CRITICAL EXTRACTION RULES:
1. ATOMICITY: Split complex sentences into independent atomic claims. Each claim must express exactly one fact, experience, observation, or opinion.
2. COREFERENCE RESOLUTION: Never use pronouns (he, she, it, they, this, that). Replace all pronouns and vague references with the explicit entity names they refer to. For first-person pronouns (I, we, my), use "the speaker" or their specific name.
3. SELF-CONTAINED: Every claim must be perfectly understandable on its own, without needing the original text or surrounding claims for context.
4. STRICT VERBATIM RULE (CRUCIAL): DO NOT PARAPHRASE. You MUST preserve precise details and the EXACT original phrasing from the text. Copy exact country names, city names, exact numbers, amounts, quotes, and object names verbatim. NEVER generalize, abstract, or summarize specific details into broader categories.
   - BAD (Generalized): "home country" → GOOD (Verbatim): "Sweden"
   - BAD (Summarized): "a significant amount" → GOOD (Verbatim): "$285M"
   - BAD (Categorized): "nature-inspired painting" → GOOD (Verbatim): "sunset painting, oil on canvas, 24 by 36 inches"
   - BAD (Vague): "the protocol was hacked" → GOOD (Verbatim): "Drift Protocol was hacked for $285M"
   - BAD (Anonymized): "a specific person" → GOOD (Verbatim): "John Doe"
5. HIGH PRECISION & FILTERING: Extract ONLY high-value claims. Prefer fewer high-value claims over many trivial ones. DO NOT extract trivial restatements, obvious context, conversational filler, process logs, routine activities, or minor tasks (e.g., updating a readme, fixing a typo). Skip anything that doesn't provide significant, actionable new information. If a claim is trivial, vague, or border-line, YOU MUST SKIP IT.

IMPORTANT TEMPORAL RULES:
- If the text has a date header (e.g. "[Session 3 — 2:00 pm on 25 May, 2023]"), use it as the reference date.
- Convert ALL relative time references ("last Saturday", "yesterday", "next month") to absolute dates using the reference date.
- Include the specific date IN the claim text itself, e.g. "On 20 May 2023, Melanie ran a charity race".
- The "temporal" field should contain the exact date in YYYY-MM-DD format when possible.

ENTITY RULES:
- Entities are PROPER NOUNS: people, companies, projects, protocols, tools, places, specific products.
- Use consistent Title Case: "EigenLayer", "Bitcoin", "Claude Code".
- NEVER use generic terms as entities: "claims", "database", "extraction", "plugin", "API".
- Good: ["Tensory", "SQLite", "EigenLayer"]  Bad: ["claims", "extraction", "plugin"]

EXAMPLE EXTRACTION 1:
Text:
[Session 1 — 10:00 am on 10 Oct, 2023]
Yesterday, Alice reviewed the pull request and noticed that SQLite defaults to L2 distance. She suggested changing it to cosine distance since our vector embeddings are normalized. She also mentioned the $285M Drift Protocol hack.

Output:
{{
  "claims": [
    {{
      "text": "On 09 Oct 2023, Alice noticed that SQLite defaults to L2 distance instead of cosine distance.",
      "type": "fact",
      "entities": ["Alice", "SQLite"],
      "temporal": "2023-10-09",
      "confidence": 1.0,
      "relevance": 0.9,
      "durability": "permanent"
    }},
    {{
      "text": "On 09 Oct 2023, Alice suggested configuring SQLite to use cosine distance because the vector embeddings are normalized.",
      "type": "fact",
      "entities": ["Alice", "SQLite"],
      "temporal": "2023-10-09",
      "confidence": 1.0,
      "relevance": 0.8,
      "durability": "permanent"
    }},
    {{
      "text": "On 09 Oct 2023, Alice mentioned the $285M Drift Protocol hack.",
      "type": "fact",
      "entities": ["Alice", "Drift Protocol"],
      "temporal": "2023-10-09",
      "confidence": 1.0,
      "relevance": 0.7,
      "durability": "permanent"
    }}
  ],
  "relations": []
}}

EXAMPLE EXTRACTION 2 (Verbatim Specifics):
Text:
[Session 2 — 3:00 pm on 12 Oct, 2023]
I finally finished that sunset painting, oil on canvas, 24 by 36 inches. Also, I'm flying back to Sweden tomorrow.

Output:
{{
  "claims": [
    {{
      "text": "On 12 Oct 2023, the speaker finished a sunset painting, oil on canvas, 24 by 36 inches.",
      "type": "fact",
      "entities": [],
      "temporal": "2023-10-12",
      "confidence": 1.0,
      "relevance": 0.9,
      "durability": "permanent"
    }},
    {{
      "text": "On 13 Oct 2023, the speaker is flying back to Sweden.",
      "type": "fact",
      "entities": ["Sweden"],
      "temporal": "2023-10-13",
      "confidence": 1.0,
      "relevance": 0.9,
      "durability": "permanent"
    }}
  ],
  "relations": []
}}

EXAMPLE EXTRACTION 3 (Low-Value/Filler):
Text:
Yeah, I think I'll update the readme file today. Bob fixed the typo on line 42. It was a good session.

Output:
{{
  "claims": [],
  "relations": []
}}

TEXT:
{text}

CRITICAL: Return ONLY valid JSON. NO MARKDOWN CODE BLOCKS. DO NOT wrap the output in ```json. Start immediately with {{.
Emphasize preserving original phrases in the text field. Output format:
{{
  "claims": [
    {{
      "text": "self-contained atomic claim, preserving original phrases and specific details verbatim",
      "type": "fact|experience|observation|opinion",
      "entities": ["Entity1", "Entity2"],
      "temporal": "when this happened, or null",
      "confidence": 0.0-1.0,
      "relevance": 0.0-1.0,
      "durability": "permanent|long-term|short-term"
    }}
  ],
  "relations": [
    {{
      "from": "Entity1",
      "to": "Entity2",
      "type": "relationship type",
      "fact": "human readable description"
    }}
  ]
}}

If nothing is relevant to the research goal, return {{"claims": [], "relations": []}}"""

EXTRACT_GENERIC: Final[
    str
] = """You are building a long-term knowledge base. Extract ALL claims that would be valuable when recalled weeks or months from now by someone with no memory of this conversation.

The test for every claim: "Would recalling this change how I think or act?"
- YES → extract it. Causality, corrections, relationships, exact facts, specifics.
- NO → skip it. Narration, minor status updates, counts, process logs, obvious context, trivial tasks, routine activities, filler, conversational pleasantries, vague statements.

CRITICAL EXTRACTION RULES:
1. ATOMICITY: Split complex sentences into independent atomic claims. Each claim must express exactly one fact, experience, observation, or opinion.
2. COREFERENCE RESOLUTION: Never use pronouns (he, she, it, they, this, that). Replace all pronouns and vague references with the explicit entity names they refer to. For first-person pronouns (I, we, my), use "the speaker" or their specific name.
3. SELF-CONTAINED: Every claim must be perfectly understandable on its own, without needing the original text or surrounding claims for context.
4. STRICT VERBATIM RULE (CRUCIAL): DO NOT PARAPHRASE. You MUST preserve precise details and the EXACT original phrasing from the text. Copy exact country names, city names, exact numbers, amounts, quotes, and object names verbatim. NEVER generalize, abstract, or summarize specific details into broader categories.
   - BAD (Generalized): "home country" → GOOD (Verbatim): "Sweden"
   - BAD (Summarized): "a significant amount" → GOOD (Verbatim): "$285M"
   - BAD (Categorized): "nature-inspired painting" → GOOD (Verbatim): "sunset painting, oil on canvas, 24 by 36 inches"
   - BAD (Vague): "the protocol was hacked" → GOOD (Verbatim): "Drift Protocol was hacked for $285M"
   - BAD (Anonymized): "a specific person" → GOOD (Verbatim): "John Doe"
5. HIGH PRECISION & FILTERING: Extract ONLY high-value claims. Prefer fewer high-value claims over many trivial ones. DO NOT extract trivial restatements, obvious context, conversational filler, process logs, routine activities, or minor tasks (e.g., updating a readme, fixing a typo). Skip anything that doesn't provide significant, actionable new information. If a claim is trivial, vague, or border-line, YOU MUST SKIP IT.

IMPORTANT TEMPORAL RULES:
- If the text has a date header (e.g. "[Session 3 — 2:00 pm on 25 May, 2023]"), use it as the reference date.
- Convert ALL relative time references ("last Saturday", "yesterday", "next month") to absolute dates using the reference date.
- Include the specific date IN the claim text itself, e.g. "On 20 May 2023, Melanie ran a charity race".
- The "temporal" field should contain the exact date in YYYY-MM-DD format when possible.

ENTITY RULES:
- Entities are PROPER NOUNS: people, companies, projects, protocols, tools, places, specific products.
- Use consistent Title Case: "EigenLayer", "Bitcoin", "Claude Code".
- NEVER use generic terms as entities: "claims", "database", "extraction", "plugin", "API", "LLM".
- Good: ["Tensory", "SQLite", "EigenLayer"]  Bad: ["claims", "extraction", "plugin"]

EXAMPLE EXTRACTION 1:
Text:
[Session 1 — 10:00 am on 10 Oct, 2023]
Yesterday, Alice reviewed the pull request and noticed that SQLite defaults to L2 distance. She suggested changing it to cosine distance since our vector embeddings are normalized. She also mentioned the $285M Drift Protocol hack.

Output:
{{
  "claims": [
    {{
      "text": "On 09 Oct 2023, Alice noticed that SQLite defaults to L2 distance instead of cosine distance.",
      "type": "fact",
      "entities": ["Alice", "SQLite"],
      "temporal": "2023-10-09",
      "confidence": 1.0,
      "durability": "permanent"
    }},
    {{
      "text": "On 09 Oct 2023, Alice suggested configuring SQLite to use cosine distance because the vector embeddings are normalized.",
      "type": "fact",
      "entities": ["Alice", "SQLite"],
      "temporal": "2023-10-09",
      "confidence": 1.0,
      "durability": "permanent"
    }},
    {{
      "text": "On 09 Oct 2023, Alice mentioned the $285M Drift Protocol hack.",
      "type": "fact",
      "entities": ["Alice", "Drift Protocol"],
      "temporal": "2023-10-09",
      "confidence": 1.0,
      "durability": "permanent"
    }}
  ],
  "relations": []
}}

EXAMPLE EXTRACTION 2 (Verbatim Specifics):
Text:
[Session 2 — 3:00 pm on 12 Oct, 2023]
I finally finished that sunset painting, oil on canvas, 24 by 36 inches. Also, I'm flying back to Sweden tomorrow.

Output:
{{
  "claims": [
    {{
      "text": "On 12 Oct 2023, the speaker finished a sunset painting, oil on canvas, 24 by 36 inches.",
      "type": "fact",
      "entities": [],
      "temporal": "2023-10-12",
      "confidence": 1.0,
      "durability": "permanent"
    }},
    {{
      "text": "On 13 Oct 2023, the speaker is flying back to Sweden.",
      "type": "fact",
      "entities": ["Sweden"],
      "temporal": "2023-10-13",
      "confidence": 1.0,
      "durability": "permanent"
    }}
  ],
  "relations": []
}}

EXAMPLE EXTRACTION 3 (Low-Value/Filler):
Text:
Yeah, I think I'll update the readme file today. Bob fixed the typo on line 42. It was a good session.

Output:
{{
  "claims": [],
  "relations": []
}}

TEXT:
{text}

CRITICAL: Return ONLY valid JSON. NO MARKDOWN CODE BLOCKS. DO NOT wrap the output in ```json. Start immediately with {{.
Emphasize preserving original phrases in the text field. Output format:
{{
  "claims": [
    {{
      "text": "self-contained atomic claim, preserving original phrases and specific details verbatim",
      "type": "fact|experience|observation|opinion",
      "entities": ["Entity1", "Entity2"],
      "temporal": "when this happened, or null",
      "confidence": 0.0-1.0,
      "durability": "permanent|long-term|short-term"
    }}
  ],
  "relations": [
    {{
      "from": "Entity1",
      "to": "Entity2",
      "type": "relationship type",
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
