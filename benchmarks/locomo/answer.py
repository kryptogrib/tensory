"""QA answering pipeline for LoCoMo benchmark.

For each question:
1. store.search(question) → top-k claims
2. Format claims as context
3. Sonnet generates answer

The answer prompt is designed to:
- Return short factual answers (matching LoCoMo gold format)
- Say "unanswerable" for questions without evidence (adversarial)
- Cite claim text for traceability
"""

from __future__ import annotations

import logging

from benchmarks.locomo.data import QAItem
from benchmarks.locomo.score import BenchmarkResult
from tensory.context import format_context
from tensory.extract import LLMProtocol
from tensory.models import Context, SearchResult
from tensory.routing import classify_query
from tensory.store import Tensory

logger = logging.getLogger(__name__)

ANSWER_PROMPT = """You are answering questions based ONLY on the provided memory claims.

CLAIMS FROM MEMORY:
{claims_text}

QUESTION: {question}

RULES:
- Answer based ONLY on the claims above
- Keep your answer SHORT — ideally 1-5 words, maximum one sentence
- If claims contain dates or time references, use them to calculate exact dates
- If you have partial evidence, give your BEST answer based on what's available
- Only say "unanswerable" if the claims contain absolutely NO relevant information
- Do NOT explain your reasoning, just give the direct answer
- For "when" questions, prefer absolute dates (e.g. "20 May 2023") over relative ones ("last Saturday")

ANSWER:"""


def _format_claims(results: list[SearchResult]) -> str:
    """Format search results as numbered claims for the prompt.

    Includes temporal metadata when available, so the answer LLM
    can reason about dates and time references.
    """
    if not results:
        return "(no relevant claims found)"

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        temporal = f" [when: {r.claim.temporal}]" if r.claim.temporal else ""
        lines.append(f"{i}. [score={r.score:.3f}]{temporal} {r.claim.text}")
    return "\n".join(lines)


async def answer_questions(
    store: Tensory,
    qa_items: list[QAItem],
    answer_llm: LLMProtocol,
    *,
    context: Context | None = None,
    search_limit: int = 10,
) -> BenchmarkResult:
    """Run QA evaluation: search + answer + score.

    Args:
        store: Tensory instance with ingested conversation.
        qa_items: List of QA items to evaluate.
        answer_llm: LLM for answer generation (Sonnet).
        context: Optional search context.
        search_limit: Number of claims to retrieve per question.

    Returns:
        BenchmarkResult with per-question F1 scores.
    """
    result = BenchmarkResult()
    total = len(qa_items)

    for i, qa in enumerate(qa_items, 1):
        logger.info("[%d/%d] Q: %s", i, total, qa.question[:80])

        # 1. Search (with memory-type routing)
        try:
            memory_type = classify_query(qa.question)
            search_results = await store.search(
                qa.question,
                context=context,
                limit=search_limit,
                memory_type=memory_type,
            )
        except Exception as exc:
            logger.error("Search failed for Q%d: %s", i, exc)
            search_results = []

        # 2. Generate answer (with structured context)
        claims_text = format_context(search_results)
        prompt = ANSWER_PROMPT.format(
            claims_text=claims_text,
            question=qa.question,
        )

        try:
            predicted = await answer_llm(prompt)
            predicted = predicted.strip()
        except Exception as exc:
            logger.error("Answer generation failed for Q%d: %s", i, exc)
            predicted = "unanswerable"

        # 3. Score
        f1 = result.add(
            category=qa.category,
            predicted=predicted,
            gold=qa.answer,
            question=qa.question,
        )

        logger.info(
            "  A: %s | Gold: %s | F1: %.2f",
            predicted[:60],
            qa.answer[:60],
            f1,
        )

    return result
