"""Deduplication via entropy-gated MinHash/LSH.

Prevents storing near-duplicate claims. Two strategies:
- Low entropy text (short, repetitive) → exact normalized match only
- High entropy text → MinHash signatures + Jaccard similarity

Deduplication logic adapted from Graphiti (Apache-2.0 License)
https://github.com/getzep/graphiti
Copyright 2024 Zep Software, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

References:
- MinHash + LSH + Jaccard: graphiti_core/utils/dedup_helpers.py
- Entropy gate: blog.getzep.com/graphiti-hits-20k-stars-mcp-server-1-0/
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from functools import lru_cache

__all__ = [
    "MinHashDedup",
    "_shannon_entropy",
    "_shingle",
    "_minhash",
    "_lsh_bands",
    "_jaccard",
    "_word_jaccard",
]


def _shannon_entropy(text: str) -> float:
    """Compute Shannon entropy of text.

    Low entropy (< 2.5) means the text is short or highly repetitive,
    making fuzzy matching unreliable. We fall back to exact match.
    """
    text = text.lower().strip()
    if not text:
        return 0.0
    c = Counter(text)
    total = len(text)
    return -sum((f / total) * math.log2(f / total) for f in c.values())


@lru_cache(maxsize=1024)
def _shingle(text: str, n: int = 3) -> frozenset[str]:
    """Generate character n-grams (shingles) from normalized text."""
    norm = " ".join(text.lower().split())
    if len(norm) < n:
        return frozenset([norm])
    return frozenset(norm[i : i + n] for i in range(len(norm) - n + 1))


def _minhash(shingles: frozenset[str], num_perm: int = 32) -> list[int]:
    """Compute MinHash signature from shingles.

    Uses MD5 hash with different seeds for each permutation.
    Smaller signatures = faster comparison, slight accuracy loss.
    """
    if not shingles:
        return [0] * num_perm
    return [
        min(int(hashlib.md5(f"{i}:{s}".encode()).hexdigest(), 16) for s in shingles)
        for i in range(num_perm)
    ]


def _lsh_bands(signature: list[int], band_size: int = 4) -> list[tuple[int, ...]]:
    """Split MinHash signature into LSH bands for candidate detection.

    Each band is a tuple of consecutive hash values. Two signatures
    that share any band are candidate duplicates.
    """
    return [tuple(signature[i : i + band_size]) for i in range(0, len(signature), band_size)]


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Compute Jaccard similarity between two shingle sets."""
    if not a and not b:
        return 1.0
    union = len(a | b)
    if union == 0:
        return 1.0
    return len(a & b) / union


def _word_jaccard(a: str, b: str) -> float:
    """Compute Jaccard similarity on word tokens (case-insensitive).

    More tolerant of single-word differences than char n-gram shingles.
    Used as fallback when char-Jaccard is in the ambiguous zone (0.7–0.9).
    """
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    union = len(words_a | words_b)
    if union == 0:
        return 1.0
    return len(words_a & words_b) / union


class MinHashDedup:
    """Entropy-gated deduplication using MinHash/LSH + Jaccard.

    Low-entropy strings (short, repetitive) use exact normalized match.
    High-entropy strings use MinHash + Jaccard with configurable threshold.

    Usage::

        dedup = MinHashDedup()
        if dedup.is_duplicate("New claim text", ["Existing claim 1", ...]):
            # skip — duplicate detected
    """

    def __init__(
        self,
        *,
        entropy_threshold: float = 2.5,
        jaccard_threshold: float = 0.9,
    ) -> None:
        self.entropy_threshold = entropy_threshold
        self.jaccard_threshold = jaccard_threshold

    def is_duplicate(self, new_text: str, existing_texts: list[str]) -> bool:
        """Check if new_text is a duplicate of any existing text.

        Args:
            new_text: The new claim text to check.
            existing_texts: List of existing claim texts to compare against.

        Returns:
            True if new_text is a duplicate of any existing text.
        """
        if not existing_texts:
            return False

        entropy = _shannon_entropy(new_text)

        if entropy < self.entropy_threshold:
            # Low entropy → exact normalized match only (fuzzy unreliable)
            norm = " ".join(new_text.lower().split())
            return any(" ".join(t.lower().split()) == norm for t in existing_texts)

        # High entropy → MinHash/LSH + Jaccard (char-level)
        new_shingles = _shingle(new_text)
        for existing in existing_texts:
            char_jaccard = _jaccard(new_shingles, _shingle(existing))
            if char_jaccard >= self.jaccard_threshold:
                return True
            # Word-level fallback: catches 1-2 word diffs that char shingles miss
            # (char 3-grams drop Jaccard ~0.16 per word change, so a 1-word diff
            # in a 12-word sentence gives ~0.84 — below 0.9 but clearly duplicate)
            if char_jaccard >= 0.7 and _word_jaccard(new_text, existing) >= 0.8:
                return True
        return False

    def find_duplicates(self, new_text: str, existing_texts: list[str]) -> list[int]:
        """Find indices of existing texts that are duplicates of new_text.

        Returns list of indices into existing_texts that are duplicates.
        """
        if not existing_texts:
            return []

        entropy = _shannon_entropy(new_text)
        duplicates: list[int] = []

        if entropy < self.entropy_threshold:
            norm = " ".join(new_text.lower().split())
            for i, text in enumerate(existing_texts):
                if " ".join(text.lower().split()) == norm:
                    duplicates.append(i)
        else:
            new_shingles = _shingle(new_text)
            for i, text in enumerate(existing_texts):
                char_jaccard = _jaccard(new_shingles, _shingle(text))
                if (
                    char_jaccard >= self.jaccard_threshold
                    or (char_jaccard >= 0.7 and _word_jaccard(new_text, text) >= 0.8)
                ):
                    duplicates.append(i)

        return duplicates
