"""F1 scoring for LoCoMo benchmark.

Implements the normalized token-level F1 from the LoCoMo paper (ACL 2024):
- Lowercase, strip articles/punctuation/whitespace
- Token-level precision/recall/F1
- Per-category and overall aggregation

Reference: Section 4.1 of arxiv.org/abs/2402.17753
"""

from __future__ import annotations

import re
import string
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from benchmarks.locomo.data import CATEGORY_NAMES


def normalize_answer(text: str) -> str:
    """Normalize answer for F1 comparison."""
    text = text.lower()
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = " ".join(text.split())
    return text.strip()


def compute_f1(gold: str, predicted: str) -> float:
    """Token-level F1 between gold and predicted answers."""
    gold_normalized = normalize_answer(gold)
    pred_normalized = normalize_answer(predicted)

    if gold_normalized == pred_normalized:
        return 1.0

    gold_tokens = gold_normalized.split()
    pred_tokens = pred_normalized.split()

    if not gold_tokens or not pred_tokens:
        return 0.0

    gold_counts = Counter(gold_tokens)
    pred_counts = Counter(pred_tokens)
    common_count = sum((gold_counts & pred_counts).values())

    if common_count == 0:
        return 0.0

    precision = common_count / len(pred_tokens)
    recall = common_count / len(gold_tokens)
    f1 = 2 * precision * recall / (precision + recall)
    return round(f1, 4)


@dataclass
class BenchmarkResult:
    """Accumulates per-question F1 scores and computes summary."""

    scores: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())

    def add(
        self,
        *,
        category: int,
        predicted: str,
        gold: str,
        question: str = "",
    ) -> float:
        """Record one QA result. Returns F1 for this question."""
        f1 = compute_f1(gold, predicted)
        self.scores.append({
            "category": category,
            "category_name": CATEGORY_NAMES.get(category, f"unknown-{category}"),
            "question": question,
            "gold": gold,
            "predicted": predicted,
            "f1": f1,
        })
        return f1

    def summary(self) -> dict[str, dict[str, Any]]:
        """Per-category and overall F1 summary."""
        result: dict[str, dict[str, Any]] = {}

        for cat_id, cat_name in CATEGORY_NAMES.items():
            cat_scores = [s for s in self.scores if s["category"] == cat_id]
            if cat_scores:
                f1_values = [float(s["f1"]) for s in cat_scores]
                result[cat_name] = {
                    "count": len(cat_scores),
                    "f1": round(sum(f1_values) / len(f1_values), 4),
                }

        if self.scores:
            all_f1 = [float(s["f1"]) for s in self.scores]
            result["overall"] = {
                "count": len(self.scores),
                "f1": round(sum(all_f1) / len(all_f1), 4),
            }

        return result
