"""Tests for LoCoMo benchmark scoring and data parsing."""

from benchmarks.locomo.data import parse_conversation


def test_parse_conversation_extracts_turns() -> None:
    """Verify we can parse a raw LoCoMo JSON entry into typed structures."""
    raw = {
        "sample_id": "conv-test",
        "conversation": {
            "speaker_a": "Alice",
            "speaker_b": "Bob",
            "session_1_date_time": "1:00 pm on 1 Jan, 2023",
            "session_1": [
                {"speaker": "Alice", "dia_id": "D1:1", "text": "Hello!"},
                {"speaker": "Bob", "dia_id": "D1:2", "text": "Hi there!"},
            ],
        },
        "qa": [
            {
                "question": "Who said hello?",
                "answer": "Alice",
                "evidence": ["D1:1"],
                "category": 1,
            }
        ],
        "event_summary": {},
        "observation": {},
        "session_summary": {},
    }
    conv = parse_conversation(raw)
    assert conv.sample_id == "conv-test"
    assert len(conv.sessions) == 1
    assert len(conv.sessions[0].turns) == 2
    assert conv.sessions[0].turns[0].speaker == "Alice"
    assert conv.sessions[0].turns[0].dia_id == "D1:1"
    assert len(conv.qa_items) == 1
    assert conv.qa_items[0].category == 1
    assert conv.qa_items[0].answer == "Alice"


def test_parse_adversarial_qa() -> None:
    """Category 5 questions have adversarial_answer instead of answer."""
    raw = {
        "sample_id": "conv-test",
        "conversation": {"speaker_a": "A", "speaker_b": "B"},
        "qa": [
            {
                "question": "Trick question?",
                "adversarial_answer": "wrong premise",
                "evidence": ["D1:1"],
                "category": 5,
            }
        ],
        "event_summary": {},
        "observation": {},
        "session_summary": {},
    }
    conv = parse_conversation(raw)
    assert conv.qa_items[0].is_adversarial
    assert conv.qa_items[0].answer == "unanswerable"


def test_session_to_text() -> None:
    """Verify session serialization for ingestion."""
    raw = {
        "sample_id": "conv-test",
        "conversation": {
            "speaker_a": "Alice",
            "speaker_b": "Bob",
            "session_1_date_time": "1:00 pm on 1 Jan, 2023",
            "session_1": [
                {"speaker": "Alice", "dia_id": "D1:1", "text": "Hello!"},
                {"speaker": "Bob", "dia_id": "D1:2", "text": "Hi!"},
            ],
        },
        "qa": [],
        "event_summary": {},
        "observation": {},
        "session_summary": {},
    }
    conv = parse_conversation(raw)
    text = conv.sessions[0].to_text()
    assert "Alice: Hello!" in text
    assert "Bob: Hi!" in text
    assert "1:00 pm on 1 Jan, 2023" in text


from benchmarks.locomo.score import BenchmarkResult, compute_f1, normalize_answer


def test_normalize_answer_strips_articles() -> None:
    assert normalize_answer("The United States") == "united states"
    assert normalize_answer("  a   cat  ") == "cat"
    assert normalize_answer("An Apple") == "apple"


def test_normalize_answer_strips_punctuation() -> None:
    assert normalize_answer("hello, world!") == "hello world"


def test_f1_exact_match() -> None:
    assert compute_f1("Alice", "Alice") == 1.0


def test_f1_partial_match() -> None:
    score = compute_f1("Alice went home", "Alice")
    assert 0.4 < score < 0.6


def test_f1_no_match() -> None:
    assert compute_f1("Alice", "Bob") == 0.0


def test_f1_adversarial_correct() -> None:
    assert compute_f1("unanswerable", "unanswerable") == 1.0


def test_f1_adversarial_wrong() -> None:
    assert compute_f1("unanswerable", "Alice went home") == 0.0


def test_benchmark_result_summary() -> None:
    result = BenchmarkResult()
    result.add(category=1, predicted="Alice", gold="Alice")
    result.add(category=1, predicted="Bob", gold="Charlie")
    result.add(category=5, predicted="unanswerable", gold="unanswerable")

    summary = result.summary()
    assert summary["overall"]["count"] == 3
    assert summary["single-hop"]["count"] == 2
    assert summary["adversarial"]["count"] == 1
    assert summary["adversarial"]["f1"] == 1.0
