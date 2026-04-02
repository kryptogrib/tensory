#!/usr/bin/env python3
"""Eval script for Weco prompt optimization of Tensory extraction.

Usage:
    uv run python eval_extraction.py [--verbose]

Output (stdout):
    f1_score: 0.8532

Weco CLI:
    weco run --source tensory/prompts.py \
        --eval-command "uv run python eval_extraction.py" \
        --metric f1_score --goal maximize --steps 50

Metric architecture:
    composite = 0.55 * claim_match_f1 + 0.25 * entity_f1 + 0.20 * temporal_accuracy

    - claim_match_f1: F1 via greedy bipartite matching of expected vs actual claims.
      Matching is based on the fraction of must_contain substrings found.
      Threshold: score >= 0.5 to count as a match.
      Negative cases (expected=[]) are penalized for any extracted claims.

    - entity_f1: set-based F1 over normalized entities from claims + relations.

    - temporal_accuracy: partial credit for timestamps via hierarchical comparison
      (exact > month > quarter > year > miss).
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Tensory project imports
# ---------------------------------------------------------------------------
from tensory.extract import LLMProtocol, extract_claims
from tensory.models import Claim, ClaimType, Context

# =========================================================================
#  Data models
# =========================================================================


@dataclass
class ExpectedClaim:
    """An expected claim in the ground truth."""

    must_contain: list[str]  # substrings (lower-case) — all must appear in claim text
    claim_type: ClaimType | None = None
    expected_entities: list[str] = field(default_factory=list)
    temporal: str | None = None  # "2024-Q2", "2023-04-15", "2023", None


@dataclass
class ExtractionTestCase:
    """A single test episode for evaluation."""

    name: str
    text: str
    context: Context | None = None
    expected_claims: list[ExpectedClaim] = field(default_factory=list)
    expected_entities: list[str] = field(default_factory=list)


# =========================================================================
#  16 test cases
# =========================================================================

# ---------- A. Preservation — 5 cases (from quality tests) ----------

_CASE_A1 = ExtractionTestCase(
    name="book_becoming_nicole",
    text=(
        "[Session date: 2023-10-13]\n"
        "Caroline: I've been reading 'Becoming Nicole' by Amy Ellis Nutt. "
        "It's about identical twins — one is transgender. Really eye-opening. "
        "I'm about halfway through and it makes me think about acceptance."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["becoming nicole"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["Caroline", "Becoming Nicole"],
            temporal="2023-10-13",
        ),
        ExpectedClaim(
            must_contain=["amy ellis nutt"],
            claim_type=ClaimType.FACT,
            expected_entities=["Becoming Nicole", "Amy Ellis Nutt"],
        ),
    ],
    expected_entities=["Caroline", "Becoming Nicole", "Amy Ellis Nutt"],
)

_CASE_A2 = ExtractionTestCase(
    name="book_nothing_is_impossible",
    text=(
        "[Session date: 2023-10-13]\n"
        "David: I just finished 'Nothing is Impossible' by Christopher Reeve. "
        "He describes his rehabilitation after the horse-riding accident "
        "and his advocacy for spinal cord research. Very inspiring."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["nothing is impossible"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["David", "Nothing is Impossible"],
        ),
        ExpectedClaim(
            must_contain=["christopher reeve"],
            claim_type=ClaimType.FACT,
            expected_entities=["Christopher Reeve"],
        ),
    ],
    expected_entities=["David", "Nothing is Impossible", "Christopher Reeve"],
)

_CASE_A3 = ExtractionTestCase(
    name="children_ages_numbers",
    text=(
        "[Session date: 2024-01-15]\n"
        "Mark: We have 3 children now — Emma is 8, Lucas is 5, and baby Sophie "
        "just turned 1. We visit my parents in Portland about twice a year, "
        "usually around Christmas and in July."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["3", "children"],
            claim_type=ClaimType.FACT,
            expected_entities=["Mark"],
        ),
        ExpectedClaim(
            must_contain=["emma", "8"],
            claim_type=ClaimType.FACT,
            expected_entities=["Emma"],
        ),
        ExpectedClaim(
            must_contain=["twice", "year", "portland"],
            claim_type=ClaimType.FACT,
            expected_entities=["Mark", "Portland"],
        ),
    ],
    expected_entities=["Mark", "Emma", "Lucas", "Sophie", "Portland"],
)

_CASE_A4 = ExtractionTestCase(
    name="instruments_family",
    text=(
        "[Session date: 2023-11-20]\n"
        "Sarah: My daughter plays clarinet in the school band and my son "
        "just switched from violin to piano. He's been taking lessons with "
        "Mrs. Henderson for about 6 months now."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["clarinet"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["violin", "piano"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["mrs. henderson"],
            claim_type=ClaimType.FACT,
            expected_entities=["Mrs. Henderson"],
        ),
    ],
    expected_entities=["Sarah", "Mrs. Henderson"],
)

_CASE_A5 = ExtractionTestCase(
    name="charlottes_web_opinion",
    text=(
        "I loved Charlotte's Web as a kid. It was my absolute favorite book. "
        "I've read it to my own children at least five times."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["charlotte's web"],
            claim_type=ClaimType.OPINION,
            expected_entities=["Charlotte's Web"],
        ),
    ],
    expected_entities=["Charlotte's Web"],
)

# ---------- B. Temporal resolution — 3 cases ----------

_CASE_B1 = ExtractionTestCase(
    name="temporal_relative_last_week",
    text=(
        "[Session date: 2024-03-15]\n"
        "Alex: I had a terrible migraine last Tuesday. The doctor prescribed "
        "sumatriptan yesterday and it helped within 30 minutes."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["migraine"],
            temporal="2024-03-12",
            expected_entities=["Alex"],
        ),
        ExpectedClaim(
            must_contain=["sumatriptan"],
            temporal="2024-03-14",
            expected_entities=["Alex"],
        ),
    ],
    expected_entities=["Alex"],
)

_CASE_B2 = ExtractionTestCase(
    name="temporal_quarter",
    text=(
        "EigenLayer launched their restaking protocol in Q2 2024. "
        "By September 2024, TVL reached $15 billion."
    ),
    context=Context(id="t1", goal="Track DeFi protocol launches", domain="crypto"),
    expected_claims=[
        ExpectedClaim(
            must_contain=["eigenlayer", "restaking"],
            temporal="2024-Q2",
            expected_entities=["EigenLayer"],
        ),
        ExpectedClaim(
            must_contain=["tvl", "15 billion"],
            temporal="2024-09",
            expected_entities=["EigenLayer"],
        ),
    ],
    expected_entities=["EigenLayer"],
)

_CASE_B3 = ExtractionTestCase(
    name="temporal_recently_unresolved",
    text="I recently started learning Rust. It's been a great experience so far.",
    expected_claims=[
        ExpectedClaim(
            must_contain=["rust", "learning"],
            # "recently" without session date -> temporal should be None
            temporal=None,
            expected_entities=["Rust"],
        ),
    ],
    expected_entities=["Rust"],
)

# ---------- C. Context relevance — 2 paired cases (same text ± context) ----------

_RELEVANCE_TEXT = (
    "Uniswap's lead developer left the project to start a new DeFi protocol. "
    "The team is also hiring three new Solidity engineers from Compound. "
    "Meanwhile, Apple released iOS 17 with new privacy features and "
    "Google launched Pixel 8 Pro with a Tensor G3 chip."
)

_CASE_C1 = ExtractionTestCase(
    name="context_with_defi_goal",
    text=_RELEVANCE_TEXT,
    context=Context(id="c1", goal="Track DeFi team movements", domain="crypto"),
    expected_claims=[
        ExpectedClaim(
            must_contain=["uniswap", "lead developer"],
            claim_type=ClaimType.FACT,
            expected_entities=["Uniswap"],
        ),
        ExpectedClaim(
            must_contain=["solidity", "compound"],
            claim_type=ClaimType.FACT,
            expected_entities=["Compound"],
        ),
        # Apple and Google should NOT appear — irrelevant to DeFi goal.
        # Penalized as FP in claim_match_f1.
    ],
    expected_entities=["Uniswap", "Compound"],
)

_CASE_C2 = ExtractionTestCase(
    name="context_no_goal_all_valuable",
    text=_RELEVANCE_TEXT,
    context=None,
    expected_claims=[
        ExpectedClaim(
            must_contain=["uniswap", "lead developer"],
            expected_entities=["Uniswap"],
        ),
        ExpectedClaim(
            must_contain=["solidity", "compound"],
            expected_entities=["Compound"],
        ),
        ExpectedClaim(
            must_contain=["apple", "ios 17"],
            expected_entities=["Apple"],
        ),
        ExpectedClaim(
            must_contain=["google", "pixel 8"],
            expected_entities=["Google"],
        ),
    ],
    expected_entities=["Uniswap", "Compound", "Apple", "Google"],
)

# ---------- D. Negative / durability — 3 cases (expected_claims=[]) ----------

_CASE_D1 = ExtractionTestCase(
    name="neg_short_term_hunger",
    text="I'm hungry right now. Going to grab a sandwich in 10 minutes.",
    expected_claims=[],
    expected_entities=[],
)

_CASE_D2 = ExtractionTestCase(
    name="neg_short_term_meeting",
    text="The meeting starts in 5 minutes. Battery is at 12%. Send the link when you can.",
    expected_claims=[],
    expected_entities=[],
)

_CASE_D3 = ExtractionTestCase(
    name="neg_vague_no_context",
    text="The issue was fixed. It works now.",
    expected_claims=[],
    expected_entities=[],
)

# ---------- E. Self-containment — 2 cases ----------

_CASE_E1 = ExtractionTestCase(
    name="self_contained_sqlite_bug",
    text=(
        "We found that sqlite-vec returns L2 distance by default instead of "
        "cosine similarity. The fix was to normalize embeddings before insertion. "
        "This affected our search relevance for about two weeks."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["sqlite-vec", "l2"],
            expected_entities=["sqlite-vec"],
        ),
        ExpectedClaim(
            must_contain=["normalize", "embeddings"],
            expected_entities=["sqlite-vec"],
        ),
    ],
    expected_entities=["sqlite-vec"],
)

_CASE_E2 = ExtractionTestCase(
    name="self_contained_lora_training",
    text=(
        "Our team discovered that using LoRA with rank 16 gives 95% of full "
        "fine-tuning quality on Llama 3. Training cost was $230 on 4×A100 GPUs. "
        "We'll use this approach for all future adapter training."
    ),
    context=Context(id="e1", goal="Track ML training techniques", domain="machine learning"),
    expected_claims=[
        ExpectedClaim(
            must_contain=["lora", "rank 16", "95%"],
            claim_type=ClaimType.FACT,
            expected_entities=["LoRA", "Llama 3"],
        ),
        ExpectedClaim(
            must_contain=["$230", "a100"],
            claim_type=ClaimType.FACT,
        ),
    ],
    expected_entities=["LoRA", "Llama 3"],
)

# ---------- F. Entity density — 1 case (stress test) ----------

_CASE_F1 = ExtractionTestCase(
    name="entity_density_partnerships",
    text=(
        "In Q1 2024, Google invested $300M in Anthropic for AI safety research. "
        "Amazon followed with a $4B investment the same quarter. "
        "Anthropic uses AWS as their primary cloud provider but also runs "
        "workloads on Google Cloud. OpenAI meanwhile raised $6.6B at a "
        "$157B valuation from Microsoft, Thrive Capital, and SoftBank."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["google", "300m", "anthropic"],
            temporal="2024-Q1",
            expected_entities=["Google", "Anthropic"],
        ),
        ExpectedClaim(
            must_contain=["amazon", "4b", "anthropic"],
            temporal="2024-Q1",
            expected_entities=["Amazon", "Anthropic"],
        ),
        ExpectedClaim(
            must_contain=["anthropic", "aws"],
            expected_entities=["Anthropic", "AWS"],
        ),
        ExpectedClaim(
            must_contain=["openai", "6.6b"],
            expected_entities=["OpenAI", "Microsoft"],
        ),
    ],
    expected_entities=[
        "Google",
        "Anthropic",
        "Amazon",
        "AWS",
        "Google Cloud",
        "OpenAI",
        "Microsoft",
        "Thrive Capital",
        "SoftBank",
    ],
)

# ---------- G. LoCoMo-inspired: Multi-hop extraction (chain-ready facts) --- 3 cases

_CASE_G1 = ExtractionTestCase(
    name="multihop_game_console",
    text=(
        "[Session date: 2023-08-10]\n"
        "Nate: I've been playing Xenoblade Chronicles 2 non-stop. "
        "It's a Switch exclusive, so I had to buy the console just for this game. "
        "My girlfriend Sarah thinks I spend too much time gaming."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["nate", "xenoblade chronicles 2"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["Nate", "Xenoblade Chronicles 2"],
            temporal="2023-08-10",
        ),
        ExpectedClaim(
            must_contain=["xenoblade chronicles 2", "switch", "exclusive"],
            claim_type=ClaimType.FACT,
            expected_entities=["Xenoblade Chronicles 2", "Switch"],
        ),
        ExpectedClaim(
            must_contain=["nate", "switch"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["Nate", "Switch"],
        ),
        ExpectedClaim(
            must_contain=["sarah", "gaming"],
            expected_entities=["Nate", "Sarah"],
        ),
    ],
    expected_entities=["Nate", "Xenoblade Chronicles 2", "Switch", "Sarah"],
)

_CASE_G2 = ExtractionTestCase(
    name="multihop_career_chain",
    text=(
        "[Session date: 2023-09-15]\n"
        "Caroline: I've decided to pursue counseling as a career, specifically "
        "mental health support for transgender people. My therapist Dr. Rivera "
        "helped me realize this was my calling. I'm applying to the MSW program "
        "at Portland State University starting next fall."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["caroline", "counseling", "transgender"],
            claim_type=ClaimType.FACT,
            expected_entities=["Caroline"],
        ),
        ExpectedClaim(
            must_contain=["dr. rivera", "therapist"],
            claim_type=ClaimType.FACT,
            expected_entities=["Caroline", "Dr. Rivera"],
        ),
        ExpectedClaim(
            must_contain=["msw", "portland state"],
            claim_type=ClaimType.FACT,
            expected_entities=["Caroline", "Portland State University"],
            temporal="2024",
        ),
    ],
    expected_entities=["Caroline", "Dr. Rivera", "Portland State University"],
)

_CASE_G3 = ExtractionTestCase(
    name="multihop_pet_vet",
    text=(
        "[Session date: 2024-02-20]\n"
        "Melanie: Shadow has been limping since last Wednesday. We took him to "
        "Dr. Park at Greenfield Veterinary Clinic. Turns out it's a torn ligament. "
        "Surgery is scheduled for March 5th and costs about $3,200."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["shadow", "limping"],
            expected_entities=["Shadow"],
            temporal="2024-02-14",
        ),
        ExpectedClaim(
            must_contain=["shadow", "dr. park", "greenfield"],
            expected_entities=["Shadow", "Dr. Park", "Greenfield Veterinary Clinic"],
        ),
        ExpectedClaim(
            must_contain=["shadow", "torn ligament"],
            claim_type=ClaimType.FACT,
            expected_entities=["Shadow"],
        ),
        ExpectedClaim(
            must_contain=["surgery", "march 5"],
            expected_entities=["Shadow"],
            temporal="2024-03-05",
        ),
        ExpectedClaim(
            must_contain=["$3,200"],
            claim_type=ClaimType.FACT,
        ),
    ],
    expected_entities=["Shadow", "Melanie", "Dr. Park", "Greenfield Veterinary Clinic"],
)

# ---------- H. LoCoMo-inspired: Detail preservation (single-hop misses) --- 3 cases

_CASE_H1 = ExtractionTestCase(
    name="detail_art_project",
    text=(
        "[Session date: 2023-07-22]\n"
        "Melanie: I finished my sunset painting last weekend. It's oil on canvas, "
        "24 by 36 inches. I used a palette knife technique I learned from "
        "a Bob Ross tutorial. Planning to enter it in the county fair in August."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["melanie", "sunset painting"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["Melanie"],
            temporal="2023-07-15",
        ),
        ExpectedClaim(
            must_contain=["oil", "canvas", "24", "36"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["palette knife", "bob ross"],
            claim_type=ClaimType.FACT,
            expected_entities=["Bob Ross"],
        ),
        ExpectedClaim(
            must_contain=["county fair", "august"],
            expected_entities=["Melanie"],
        ),
    ],
    expected_entities=["Melanie", "Bob Ross"],
)

_CASE_H2 = ExtractionTestCase(
    name="detail_event_list",
    text=(
        "[Session date: 2023-06-30]\n"
        "Caroline: This year I participated in the Pride parade downtown, "
        "gave a speech at school about LGBTQ+ rights, joined the Trans Alliance "
        "support group, and started volunteering at the Rainbow Youth Center "
        "every Saturday."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["caroline", "pride parade"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["Caroline"],
        ),
        ExpectedClaim(
            must_contain=["speech", "school", "lgbtq"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["Caroline"],
        ),
        ExpectedClaim(
            must_contain=["trans alliance", "support group"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["Caroline", "Trans Alliance"],
        ),
        ExpectedClaim(
            must_contain=["rainbow youth center", "saturday"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["Caroline", "Rainbow Youth Center"],
        ),
    ],
    expected_entities=["Caroline", "Trans Alliance", "Rainbow Youth Center"],
)

_CASE_H3 = ExtractionTestCase(
    name="detail_relationship_status",
    text=(
        "[Session date: 2023-11-08]\n"
        "David: I broke up with Emily in September. We dated for three years. "
        "She moved to Chicago for a job at McKinsey. I've started seeing someone "
        "new — her name is Priya, she's a pediatrician at Children's Hospital."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["david", "emily", "broke up"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["David", "Emily"],
            temporal="2023-09",
        ),
        ExpectedClaim(
            must_contain=["david", "emily", "three years"],
            claim_type=ClaimType.FACT,
            expected_entities=["David", "Emily"],
        ),
        ExpectedClaim(
            must_contain=["emily", "chicago", "mckinsey"],
            claim_type=ClaimType.FACT,
            expected_entities=["Emily", "Chicago", "McKinsey"],
        ),
        ExpectedClaim(
            must_contain=["david", "priya"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["David", "Priya"],
        ),
        ExpectedClaim(
            must_contain=["priya", "pediatrician", "children's hospital"],
            claim_type=ClaimType.FACT,
            expected_entities=["Priya", "Children's Hospital"],
        ),
    ],
    expected_entities=["David", "Emily", "Chicago", "McKinsey", "Priya", "Children's Hospital"],
)

# ---------- I. LoCoMo-inspired: Temporal arithmetic (relative dates) --- 2 cases

_CASE_I1 = ExtractionTestCase(
    name="temporal_complex_relative",
    text=(
        "[Session 7 — 2:00 pm on 25 May, 2023]\n"
        "Melanie: I ran a 5K charity race the Sunday before last. "
        "And three weeks ago I signed up for a half marathon in October. "
        "My coach wants me to do a practice run next Saturday."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["melanie", "5k", "charity race"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["Melanie"],
            temporal="2023-05-14",
        ),
        ExpectedClaim(
            must_contain=["melanie", "half marathon", "october"],
            expected_entities=["Melanie"],
        ),
        ExpectedClaim(
            must_contain=["practice run"],
            expected_entities=["Melanie"],
            temporal="2023-06-03",
        ),
    ],
    expected_entities=["Melanie"],
)

_CASE_I2 = ExtractionTestCase(
    name="temporal_seasonal_plans",
    text=(
        "[Session date: 2023-04-12]\n"
        "Sarah: We're planning a camping trip for the summer, probably late July. "
        "Last Christmas we went to my parents' cabin in Vermont. "
        "The kids want to go back there again this Thanksgiving."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["camping", "summer", "july"],
            expected_entities=["Sarah"],
        ),
        ExpectedClaim(
            must_contain=["cabin", "vermont", "christmas"],
            claim_type=ClaimType.EXPERIENCE,
            expected_entities=["Sarah", "Vermont"],
            temporal="2022-12",
        ),
        ExpectedClaim(
            must_contain=["thanksgiving", "vermont"],
            expected_entities=["Sarah", "Vermont"],
            temporal="2023-11",
        ),
    ],
    expected_entities=["Sarah", "Vermont"],
)

# ---------- J. LoCoMo-inspired: Entity crowding (popular vs rare facts) --- 1 case

_CASE_J1 = ExtractionTestCase(
    name="entity_crowding_session",
    text=(
        "[Session date: 2024-01-20]\n"
        "Caroline: Therapy with Dr. Rivera has been really helpful. "
        "We've been working on my anxiety for months now. "
        "Oh, and I almost forgot — my brother Jake got accepted to MIT! "
        "He's going to study aerospace engineering starting in September."
    ),
    expected_claims=[
        ExpectedClaim(
            must_contain=["caroline", "therapy", "dr. rivera"],
            expected_entities=["Caroline", "Dr. Rivera"],
        ),
        ExpectedClaim(
            must_contain=["caroline", "anxiety"],
            expected_entities=["Caroline"],
        ),
        ExpectedClaim(
            must_contain=["jake", "mit"],
            claim_type=ClaimType.FACT,
            expected_entities=["Jake", "MIT"],
        ),
        ExpectedClaim(
            must_contain=["jake", "aerospace engineering"],
            claim_type=ClaimType.FACT,
            expected_entities=["Jake"],
            temporal="2024-09",
        ),
    ],
    expected_entities=["Caroline", "Dr. Rivera", "Jake", "MIT"],
)

# ---------- K. Real-world: TG crypto/politics posts (Russian) --- 2 cases

_CASE_K1 = ExtractionTestCase(
    name="tg_drift_hack",
    text=(
        "[2026-03-28]\n"
        "Взлом Drift Protocol\n\n"
        "Думаю, вчера все слышали о том, что Drift (https://x.com/DriftProtocol) "
        "был взломан на $285М и потерял более 50% своего TVL. Решил разобрать "
        "ситуацию, может кому-то будет интересно.\n\n"
        "Атака началась с компрометации ключей команды, скамеры получили доступ к "
        "управлению параметрами протокола. Использовалась хитрая механика Solana, "
        "позволяющая заранее подписывать транзакции и «выстреливать» ими пачкой, "
        "обходя лимиты безопастности.\n\n"
        "Хакер опустошил пулы JLP, USDC и cbBTC. Из интересного украденные средства "
        "сразу ушли на Jupiter и мосты в сеть Ethereum (он закупил ETH).\n\n"
        "На новости о взломе $DRIFT сложился на 40%, самые смартики успели зашортить "
        "и заработать неплохую котлету."
    ),
    context=Context(id="k1", goal="Track DeFi security incidents", domain="crypto"),
    expected_claims=[
        ExpectedClaim(
            must_contain=["drift", "285"],
            claim_type=ClaimType.FACT,
            expected_entities=["Drift"],
            temporal="2026-03-27",
        ),
        ExpectedClaim(
            must_contain=["drift", "tvl", "50%"],
            claim_type=ClaimType.FACT,
            expected_entities=["Drift"],
        ),
        ExpectedClaim(
            must_contain=["key", "compromis"],
            claim_type=ClaimType.FACT,
            expected_entities=["Drift"],
        ),
        ExpectedClaim(
            must_contain=["solana"],
            claim_type=ClaimType.FACT,
            expected_entities=["Solana"],
        ),
        ExpectedClaim(
            must_contain=["jupiter", "ethereum"],
            claim_type=ClaimType.FACT,
            expected_entities=["Jupiter", "Ethereum"],
        ),
        ExpectedClaim(
            must_contain=["drift", "40%"],
            claim_type=ClaimType.FACT,
            expected_entities=["Drift"],
        ),
    ],
    expected_entities=["Drift", "Solana", "Jupiter", "Ethereum"],
)

_CASE_K2 = ExtractionTestCase(
    name="tg_trump_iran_markets",
    text=(
        "[2026-03-28]\n"
        "Выступление Дональда Трампа по ситуации в Иране (снова) обрушило рынки "
        "и запампило нефть выше $100.\n\n"
        "По словам президента США, страны, использующие Ормузский пролив, сами "
        "должны позаботиться о его безопасности. Одновременно он назвал НАТО "
        "«бумажным тигром», отметив, что США не нужен этот альянс.\n\n"
        "Альтернативный вариант — Трамп предложил странам, которые страдают от "
        "роста цен на нефть, закупать ее у США.\n\n"
        "Неопределенность всего выступления обрушила S&P500 и биткоин. Курс "
        "последнего протестировал $66 000, обрушив весь рынок. Суточные "
        "ликвидации — $420 млн."
    ),
    context=Context(id="k2", goal="Track macro events affecting crypto", domain="crypto"),
    expected_claims=[
        ExpectedClaim(
            must_contain=["trump", "iran", "oil", "100"],
            claim_type=ClaimType.FACT,
            expected_entities=["Trump"],
            temporal="2026-03-28",
        ),
        ExpectedClaim(
            must_contain=["hormuz", "strait"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["nato", "paper tiger"],
            claim_type=ClaimType.FACT,
            expected_entities=["NATO"],
        ),
        ExpectedClaim(
            must_contain=["s&p", "500"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["bitcoin", "66"],
            claim_type=ClaimType.FACT,
            expected_entities=["Bitcoin"],
        ),
        ExpectedClaim(
            must_contain=["liquidat", "420"],
            claim_type=ClaimType.FACT,
        ),
    ],
    expected_entities=["Trump", "NATO", "Iran"],
)

# ---------- L. Real-world: Russian crypto regulation TG post --- 1 case

_CASE_L1 = ExtractionTestCase(
    name="tg_russia_crypto_law",
    text=(
        "[2026-03-28]\n"
        "Правительство РФ внесло в Госдуму проект федерального закона "
        "«О цифровой валюте и цифровых правах». Документ опубликован "
        "в электронной базе Государственной Думы.\n\n"
        "Законопроектом вводится понятия «обращение» и «организация обращения» "
        "цифровой валюты, определяются ключевые участники рынка, меры по надзору "
        "и лимиты. Банк России наделяется полномочиями по допуску, регулированию "
        "и надзору за организаторами обращения цифровой валюты и цифровых прав. "
        "Большинство статей закона вступит в силу 1 июля 2026 года."
    ),
    context=Context(id="l1", goal="Track crypto regulation", domain="crypto"),
    expected_claims=[
        ExpectedClaim(
            must_contain=["duma", "digital", "currenc"],
            claim_type=ClaimType.FACT,
            temporal="2026-03-28",
        ),
        ExpectedClaim(
            must_contain=["bank of russia"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["july", "2026"],
            claim_type=ClaimType.FACT,
            temporal="2026-07-01",
        ),
    ],
    expected_entities=["State Duma", "Bank of Russia"],
)

# ---------- M. Real-world: ML research paper (English, long) --- 2 cases

_CASE_M1 = ExtractionTestCase(
    name="paper_llm_decisions_abstract",
    text=(
        "We consider the question: when a large language reasoning model makes a "
        "choice, did it think first and then decide to, or decide first and then "
        "think? In this paper, we present evidence that detectable, early-encoded "
        "decisions shape chain-of-thought in reasoning models. Specifically, we "
        "show that a simple linear probe successfully decodes tool-calling decisions "
        "from pre-generation activations with very high confidence, and in some "
        "cases, even before a single reasoning token is produced. Activation "
        "steering supports this causally: perturbing the decision direction leads "
        "to inflated deliberation, and flips behavior in many examples (between "
        "7 - 79% depending on model and benchmark). We also show through behavioral "
        "analysis that, when steering changes the decision, the chain-of-thought "
        "process often rationalizes the flip rather than resisting it."
    ),
    context=Context(id="m1", goal="Track ML interpretability research", domain="machine learning"),
    expected_claims=[
        ExpectedClaim(
            must_contain=["linear probe", "tool-calling", "pre-generation"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["activation steering", "flip", "7", "79%"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["chain-of-thought", "rationalize"],
            claim_type=ClaimType.OBSERVATION,
        ),
    ],
    expected_entities=[],
)

_CASE_M2 = ExtractionTestCase(
    name="paper_mcts_results",
    text=(
        "We introduce negative early exit, which prunes unproductive MCTS "
        "trajectories, and an adaptive boosting mechanism that reallocates "
        "reclaimed computation to reduce resource contention among concurrent "
        "searches. Integrated into vLLM, these techniques substantially reduce "
        "p99 end-to-end latency while improving throughput and maintaining "
        "reasoning accuracy. Built on vLLM and evaluated on Qwen-2.5 and "
        "Llama-3.1, it achieves up to 2.83x lower p99 end-to-end latency "
        "than serial MCTS and up to 1.46x lower latency than systems using "
        "positive early exit alone, while increasing throughput by up to "
        "2.44x without sacrificing reasoning accuracy."
    ),
    context=Context(id="m2", goal="Track ML inference optimization", domain="machine learning"),
    expected_claims=[
        ExpectedClaim(
            must_contain=["negative early exit", "mcts"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["vllm", "p99"],
            claim_type=ClaimType.FACT,
            expected_entities=["vLLM"],
        ),
        ExpectedClaim(
            must_contain=["2.83", "latency"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["qwen-2.5"],
            claim_type=ClaimType.FACT,
            expected_entities=["Qwen-2.5"],
        ),
        ExpectedClaim(
            must_contain=["2.44", "throughput"],
            claim_type=ClaimType.FACT,
        ),
    ],
    expected_entities=["vLLM", "Qwen-2.5", "Llama-3.1", "MCTS"],
)

# ---------- N. Real-world: Crypto arbitrage article (Russian, long) --- 1 case

_CASE_N1 = ExtractionTestCase(
    name="article_crypto_arbitrage",
    text=(
        "Арбитраж криптовалюты — это несколько логически связанных сделок, "
        "направленных на извлечение прибыли из разницы в ценах на одинаковые "
        "или связанные активы в одно и то же время на разных биржах или на "
        "разных рынках одной и той же платформы.\n\n"
        "Крупнейший американский банк Bank of America после крупного "
        "исследования крипторынка заявил, что 90% людей будут покупать крипту "
        "во время спада, а Boston Consulting Group вообще считает, что к 2030 "
        "году криптовалютами будет пользоваться более одного миллиарда людей.\n\n"
        "Виды арбитража: внутрибиржевой (перепродажа внутри одной биржи), "
        "межбиржевой (покупка на одной бирже, продажа на другой) и международный "
        "(между биржами разных стран). На международном рынке сейчас наиболее "
        "выгодно заниматься арбитражем из-за сложившейся политической обстановки.\n\n"
        "Блокировки по 115 ФЗ («О противодействии легализации доходов, полученных "
        "преступным путем») — главный юридический риск. Для банка важно понимать "
        "«экономическую целесообразность ваших действий»."
    ),
    context=Context(id="n1", goal="Track crypto trading strategies", domain="crypto"),
    expected_claims=[
        ExpectedClaim(
            must_contain=["arbitrage", "profit", "price differ"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["bank of america", "90%"],
            claim_type=ClaimType.FACT,
            expected_entities=["Bank of America"],
        ),
        ExpectedClaim(
            must_contain=["boston consulting", "2030", "billion"],
            claim_type=ClaimType.FACT,
            expected_entities=["Boston Consulting Group"],
        ),
        ExpectedClaim(
            must_contain=["inter-exchange"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["international", "arbitrage"],
            claim_type=ClaimType.FACT,
        ),
        ExpectedClaim(
            must_contain=["115"],
            claim_type=ClaimType.FACT,
        ),
    ],
    expected_entities=["Bank of America", "Boston Consulting Group"],
)

# ---------- Collect all cases ----------

TEST_CASES: list[ExtractionTestCase] = [
    # A. Preservation (5)
    _CASE_A1,
    _CASE_A2,
    _CASE_A3,
    _CASE_A4,
    _CASE_A5,
    # B. Temporal (3)
    _CASE_B1,
    _CASE_B2,
    _CASE_B3,
    # C. Context relevance (2)
    _CASE_C1,
    _CASE_C2,
    # D. Negative (3)
    _CASE_D1,
    _CASE_D2,
    _CASE_D3,
    # E. Self-containment (2)
    _CASE_E1,
    _CASE_E2,
    # F. Entity density (1)
    _CASE_F1,
    # G. Multi-hop extraction (3) — LoCoMo-inspired
    _CASE_G1,
    _CASE_G2,
    _CASE_G3,
    # H. Detail preservation (3) — LoCoMo single-hop misses
    _CASE_H1,
    _CASE_H2,
    _CASE_H3,
    # I. Temporal arithmetic (2) — LoCoMo relative dates
    _CASE_I1,
    _CASE_I2,
    # J. Entity crowding (1) — LoCoMo popular vs rare
    _CASE_J1,
    # K. TG posts — crypto/politics (2) — real-world Russian
    _CASE_K1,
    _CASE_K2,
    # L. TG post — crypto regulation (1) — real-world Russian
    _CASE_L1,
    # M. ML papers — English research (2) — real-world long-form
    _CASE_M1,
    _CASE_M2,
    # N. Crypto article — Russian education (1) — real-world long-form
    _CASE_N1,
]

assert len(TEST_CASES) == 31, f"Expected 31 cases, got {len(TEST_CASES)}"


# =========================================================================
#  Normalization and scoring functions
# =========================================================================


def _norm(text: str) -> str:
    """Soft normalization for comparison: lowercase, collapse whitespace."""
    # normalize_answer from locomo strips articles and punctuation — too
    # aggressive for entity matching. We use a lighter normalization here.
    return re.sub(r"\s+", " ", text.lower().strip())


def _norm_entity(entity: str) -> str:
    """Normalize entity: lowercase, strip quotes and whitespace."""
    e = entity.lower().strip().strip("'\"")
    e = re.sub(r"\s+", " ", e)
    return e


def must_contain_score(pred_text: str, expected: ExpectedClaim) -> float:
    """Fraction of required substrings found in the claim text."""
    if not expected.must_contain:
        return 1.0
    text_lower = _norm(pred_text)
    found = sum(1 for s in expected.must_contain if s.lower() in text_lower)
    return found / len(expected.must_contain)


def temporal_score(pred_temporal: str | None, gold_temporal: str | None) -> float:
    """Hierarchical comparison of temporal markers.

    exact match      → 1.0
    same month       → 0.8
    same quarter     → 0.6
    same year        → 0.3
    None == None     → 1.0
    one None         → 0.0
    """
    if pred_temporal is None and gold_temporal is None:
        return 1.0
    if pred_temporal is None or gold_temporal is None:
        return 0.0

    p, g = _norm(pred_temporal), _norm(gold_temporal)
    if p == g:
        return 1.0

    # Extract year
    p_year = re.match(r"(\d{4})", p)
    g_year = re.match(r"(\d{4})", g)
    if not p_year or not g_year:
        return 0.0
    if p_year.group(1) != g_year.group(1):
        return 0.0

    # Year matches — check finer granularity
    # Check quarter (Q1-Q4)
    p_q = re.search(r"q([1-4])", p)
    g_q = re.search(r"q([1-4])", g)

    # Check month
    p_m = re.search(r"\d{4}-(\d{2})", p)
    g_m = re.search(r"\d{4}-(\d{2})", g)

    # Month → quarter for cross-format comparison
    def month_to_q(m: int) -> int:
        return (m - 1) // 3 + 1

    p_quarter = int(p_q.group(1)) if p_q else (month_to_q(int(p_m.group(1))) if p_m else None)
    g_quarter = int(g_q.group(1)) if g_q else (month_to_q(int(g_m.group(1))) if g_m else None)

    # If both have month — compare
    if p_m and g_m and p_m.group(1) == g_m.group(1):
        # Same month but days/format differ
        return 0.8

    # If quarter matches
    if p_quarter and g_quarter and p_quarter == g_quarter:
        return 0.6

    # Only year matched
    return 0.3


def entity_set_f1(
    gold_entities: set[str],
    pred_entities: set[str],
) -> float:
    """Set-based F1 over normalized entities.

    Uses soft matching: a gold entity is considered found if at least one
    predicted entity contains it as a substring (or vice versa).
    This handles cases like "Goldman Sachs" vs "Goldman".
    """
    if not gold_entities and not pred_entities:
        return 1.0
    if not gold_entities or not pred_entities:
        return 0.0

    def _soft_match(needle: str, haystack_set: set[str]) -> bool:
        # Require exact match for short entities (<=4 chars) to avoid
        # false positives like "aws" matching "laws"
        if len(needle) <= 4:
            return needle in haystack_set
        return any(needle in h or h in needle for h in haystack_set)

    tp_recall = sum(1 for g in gold_entities if _soft_match(g, pred_entities))
    tp_precision = sum(1 for p in pred_entities if _soft_match(p, gold_entities))

    recall = tp_recall / len(gold_entities)
    precision = tp_precision / len(pred_entities)

    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


# =========================================================================
#  Greedy bipartite matching
# =========================================================================

# Minimum must_contain_score to count as a match.
# 0.7 means: at least 70% of required substrings must be found.
# Raised from 0.5 to reduce false positive matches.
MATCH_THRESHOLD = 0.7


@dataclass
class MatchResult:
    """Result of matching for a single test case."""

    matches: list[tuple[int, int, float]]  # (pred_idx, exp_idx, score)
    unmatched_pred: list[int]
    unmatched_exp: list[int]


def greedy_match_claims(
    pred_claims: list[Claim],
    expected_claims: list[ExpectedClaim],
) -> MatchResult:
    """Greedy bipartite matching: sort all pairs by must_contain_score,
    take the best unused pairs with score >= MATCH_THRESHOLD.
    """
    if not expected_claims:
        return MatchResult(
            matches=[],
            unmatched_pred=list(range(len(pred_claims))),
            unmatched_exp=[],
        )

    # Score matrix
    pairs: list[tuple[float, int, int]] = []
    for i, pred in enumerate(pred_claims):
        for j, exp in enumerate(expected_claims):
            s = must_contain_score(pred.text, exp)
            if s >= MATCH_THRESHOLD:
                pairs.append((s, i, j))

    pairs.sort(reverse=True, key=lambda x: x[0])

    matched_pred: set[int] = set()
    matched_exp: set[int] = set()
    matches: list[tuple[int, int, float]] = []

    for s, i, j in pairs:
        if i not in matched_pred and j not in matched_exp:
            matches.append((i, j, s))
            matched_pred.add(i)
            matched_exp.add(j)

    return MatchResult(
        matches=matches,
        unmatched_pred=[i for i in range(len(pred_claims)) if i not in matched_pred],
        unmatched_exp=[j for j in range(len(expected_claims)) if j not in matched_exp],
    )


# =========================================================================
#  Single case evaluation
# =========================================================================


@dataclass
class CaseScore:
    """Evaluation result for a single test case."""

    name: str
    claim_f1: float
    entity_f1: float
    temporal_acc: float
    # Diagnostics (for verbose mode)
    num_predicted: int = 0
    num_expected: int = 0
    num_matched: int = 0
    details: str = ""


async def evaluate_case(
    case: ExtractionTestCase,
    llm: LLMProtocol,
    verbose: bool = False,
) -> CaseScore:
    """Evaluate a single test case."""
    try:
        claims, relations = await extract_claims(
            case.text,
            llm,
            context=case.context,
        )
    except Exception as e:
        if verbose:
            print(f"  ERROR [{case.name}]: {e}", file=sys.stderr)
        return CaseScore(name=case.name, claim_f1=0.0, entity_f1=0.0, temporal_acc=0.0)

    diag_lines: list[str] = []

    # ------------------------------------------------------------------
    # 1. claim_match_f1
    # ------------------------------------------------------------------
    is_negative = len(case.expected_claims) == 0

    if is_negative:
        # Negative case: penalize for each extracted claim.
        # Graduated: 0 claims → 1.0, 1 → 0.7, 2 → 0.4, 3+ → 0.0
        claim_f1 = max(0.0, 1.0 - 0.3 * len(claims))
        mr = MatchResult(matches=[], unmatched_pred=list(range(len(claims))), unmatched_exp=[])
        if verbose:
            diag_lines.append(
                f"  Negative case: {len(claims)} claims extracted "
                f"(penalty → claim_f1={claim_f1:.2f})"
            )
    else:
        mr = greedy_match_claims(claims, case.expected_claims)
        tp = len(mr.matches)
        fp = len(mr.unmatched_pred)
        fn = len(mr.unmatched_exp)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        claim_f1 = (
            2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        )
        if verbose:
            diag_lines.append(
                f"  Claims: predicted={len(claims)}, expected={len(case.expected_claims)}, "
                f"matched={tp}, FP={fp}, FN={fn} → P={precision:.2f} R={recall:.2f} F1={claim_f1:.2f}"
            )

    # ------------------------------------------------------------------
    # 2. entity_f1
    # ------------------------------------------------------------------
    gold_entities = {_norm_entity(e) for e in case.expected_entities}
    pred_entities: set[str] = set()
    for c in claims:
        pred_entities.update(_norm_entity(e) for e in c.entities)
    for r in relations:
        pred_entities.add(_norm_entity(r.from_entity))
        pred_entities.add(_norm_entity(r.to_entity))

    ent_f1 = entity_set_f1(gold_entities, pred_entities)

    if verbose and case.expected_entities:
        missing = gold_entities - pred_entities
        extra = pred_entities - gold_entities
        diag_lines.append(f"  Entities: gold={sorted(gold_entities)}, pred={sorted(pred_entities)}")
        if missing:
            diag_lines.append(f"    MISSING: {sorted(missing)}")
        if extra:
            diag_lines.append(f"    EXTRA:   {sorted(extra)}")
        diag_lines.append(f"    entity_f1={ent_f1:.2f}")

    # ------------------------------------------------------------------
    # 3. temporal_accuracy (only for matched claims with temporal expectation)
    # ------------------------------------------------------------------
    temporal_scores: list[float] = []

    if not is_negative:
        exp_to_pred = {j: i for i, j, _ in mr.matches}
        for j, exp in enumerate(case.expected_claims):
            if exp.temporal is None:
                continue
            if j in exp_to_pred:
                pred_claim = claims[exp_to_pred[j]]
                ts = temporal_score(pred_claim.temporal, exp.temporal)
                temporal_scores.append(ts)
                if verbose:
                    diag_lines.append(
                        f"  Temporal: expected={exp.temporal!r}, "
                        f"predicted={pred_claim.temporal!r} → {ts:.1f}"
                    )
            else:
                # Expected claim was not found — temporal also missing.
                # Already penalized via claim_f1, no double penalty.
                pass

    temporal_acc = (
        sum(temporal_scores) / len(temporal_scores)
        if temporal_scores
        else 1.0  # no temporal expectations → consider OK
    )

    # ------------------------------------------------------------------
    # Verbose: extracted claims
    # ------------------------------------------------------------------
    if verbose:
        diag_lines.insert(0, f"\n{'=' * 60}")
        diag_lines.insert(1, f"Case: {case.name}")
        diag_lines.insert(2, f"{'=' * 60}")
        for idx, c in enumerate(claims):
            marker = ""
            for pi, ej, sc in mr.matches:
                if pi == idx:
                    marker = f"  ← matched exp[{ej}] (score={sc:.2f})"
                    break
            diag_lines.append(
                f"  [{idx}] {c.text[:120]} | type={c.type} | temporal={c.temporal}{marker}"
            )
        if mr.unmatched_exp:
            diag_lines.append(f"  UNMATCHED expected: {mr.unmatched_exp}")
            for j in mr.unmatched_exp:
                diag_lines.append(
                    f"    exp[{j}]: must_contain={case.expected_claims[j].must_contain}"
                )
        diag_lines.append(
            f"  SCORE: claim_f1={claim_f1:.3f}  entity_f1={ent_f1:.3f}  "
            f"temporal_acc={temporal_acc:.3f}"
        )
        print("\n".join(diag_lines), file=sys.stderr)

    return CaseScore(
        name=case.name,
        claim_f1=claim_f1,
        entity_f1=ent_f1,
        temporal_acc=temporal_acc,
        num_predicted=len(claims),
        num_expected=len(case.expected_claims),
        num_matched=len(mr.matches),
        details="\n".join(diag_lines),
    )


# =========================================================================
#  Main
# =========================================================================

# Metric component weights
W_CLAIM = 0.55
W_ENTITY = 0.25
W_TEMPORAL = 0.20


async def main_async(verbose: bool = False) -> None:
    from typing import cast

    from examples.llm_adapters import anthropic_from_env

    llm = cast(LLMProtocol, anthropic_from_env())
    semaphore = asyncio.Semaphore(5)

    async def _run(case: ExtractionTestCase) -> CaseScore:
        async with semaphore:
            return await evaluate_case(case, llm, verbose)

    results: list[CaseScore] = await asyncio.gather(*[_run(c) for c in TEST_CASES])

    # Aggregation
    n = len(results)
    avg_claim = sum(r.claim_f1 for r in results) / n
    avg_entity = sum(r.entity_f1 for r in results) / n
    avg_temporal = sum(r.temporal_acc for r in results) / n

    composite = W_CLAIM * avg_claim + W_ENTITY * avg_entity + W_TEMPORAL * avg_temporal

    if verbose:
        print(f"\n{'#' * 60}", file=sys.stderr)
        print(f"# AGGREGATE ({n} cases)", file=sys.stderr)
        print(f"#   avg claim_f1:    {avg_claim:.4f}  (weight {W_CLAIM})", file=sys.stderr)
        print(f"#   avg entity_f1:   {avg_entity:.4f}  (weight {W_ENTITY})", file=sys.stderr)
        print(f"#   avg temporal_acc:{avg_temporal:.4f}  (weight {W_TEMPORAL})", file=sys.stderr)
        print(f"#   COMPOSITE:       {composite:.4f}", file=sys.stderr)
        print(f"{'#' * 60}\n", file=sys.stderr)

        # Per-case summary table
        print(
            f"{'Case':<38} {'claim':>6} {'ent':>6} {'temp':>6} {'#P':>4} {'#E':>4} {'#M':>4}",
            file=sys.stderr,
        )
        print("-" * 74, file=sys.stderr)
        for r in results:
            print(
                f"{r.name:<38} {r.claim_f1:>6.3f} {r.entity_f1:>6.3f} "
                f"{r.temporal_acc:>6.3f} {r.num_predicted:>4} {r.num_expected:>4} {r.num_matched:>4}",
                file=sys.stderr,
            )

    # Single line to stdout — for Weco to parse
    print(f"f1_score: {composite:.4f}")


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Eval extraction quality for Weco prompt optimization.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed diagnostics to stderr.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args.verbose))
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
