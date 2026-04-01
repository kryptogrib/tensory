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

Extract claims that are RELEVANT to the research goal and would be valuable when recalled \
weeks or months from now by someone with no memory of this conversation.

The test for every claim: "Would recalling this change how I think or act on this research goal?"
Write each claim to be SELF-CONTAINED — understandable without the original text.

VERBATIM PRESERVATION — NEVER paraphrase proper nouns, specific objects, locations, or quantities. \
Use the speaker's EXACT words for names, numbers, colors, and specific objects. \
If the text says "Sweden", write "Sweden" — NOT "home country". \
If the text says "sunset", write "sunset" — NOT "nature-inspired". \
When in doubt, QUOTE the original words rather than summarize.

For each claim, rate its relevance to the research goal (0.0-1.0).

TEXT:
{text}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "claims": [
    {{
      "text": "self-contained atomic claim",
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
] = """You are building a long-term knowledge base. Extract claims that would be \
valuable when recalled weeks or months from now by someone with no memory of this conversation.

The test for every claim: "Would recalling this change how I think or act?"
- YES → extract it. Causality, corrections, relationships, how things work, why decisions were made.
- NO → skip it. Narration, status updates, counts, process logs, things obvious from context.

Write each claim to be SELF-CONTAINED — understandable without the original text.

VERBATIM PRESERVATION — NEVER paraphrase proper nouns, specific objects, locations, or quantities. \
Use the speaker's EXACT words for names, numbers, colors, and specific objects. \
If the text says "Sweden", write "Sweden" — NOT "home country". \
If the text says "sunset", write "sunset" — NOT "nature-inspired". \
When in doubt, QUOTE the original words rather than summarize.

Bad:  "The issue was fixed by changing line 240"
Good: "sqlite-vec returns L2 distance by default, not cosine — schema must set distance_metric=cosine explicitly"

TEXT:
{text}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "claims": [
    {{
      "text": "self-contained atomic claim",
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
