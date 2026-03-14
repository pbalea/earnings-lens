import pytest
from app.services.parser import segment_transcript

PREPARED = (
    "Good morning everyone. Welcome to the Q3 earnings call. "
    "We delivered strong revenue growth of 18% year over year. "
    "Our operating margin expanded by 200 basis points."
)

QA_SECTION = (
    "Question and Answer Session\n"
    "Operator: Our first question comes from Jane at Goldman Sachs.\n"
    "Jane: Can you expand on the margin guidance?\n"
    "CEO: Sure, we expect continued improvement."
)

FULL_TRANSCRIPT = f"{PREPARED}\n\n{QA_SECTION}"


class TestSegmentTranscript:
    def test_splits_on_question_and_answer_session(self):
        result = segment_transcript(FULL_TRANSCRIPT)
        assert PREPARED.strip() in result["prepared_remarks"]
        assert "Question and Answer Session" in result["qa_block"]

    def test_no_qa_boundary_returns_full_text_as_remarks(self):
        plain = "We had a great quarter. Revenue was $5B."
        result = segment_transcript(plain)
        assert result["prepared_remarks"] == plain
        assert result["qa_block"] == ""

    def test_splits_on_qanda_abbreviated(self):
        text = "Earnings grew 12%.\n\nQ&A Session\nAnalyst: What about margins?"
        result = segment_transcript(text)
        assert result["prepared_remarks"].endswith("12%.")
        assert "Q&A Session" in result["qa_block"]

    def test_splits_on_operator_thank_you(self):
        text = "Strong results this quarter.\nOperator: Thank you. We will now take questions."
        result = segment_transcript(text)
        assert "Strong results" in result["prepared_remarks"]
        assert "Operator: Thank you" in result["qa_block"]

    def test_splits_on_we_will_now_begin_the_question(self):
        text = "Revenue was $10B.\nWe will now begin the question-and-answer portion."
        result = segment_transcript(text)
        assert result["prepared_remarks"].endswith("$10B.")
        assert "We will now begin" in result["qa_block"]

    def test_case_insensitive_boundary_detection(self):
        text = "Remarks here.\nQUESTION AND ANSWER\nQ: Hello?"
        result = segment_transcript(text)
        assert result["prepared_remarks"].endswith("Remarks here.")
        assert "QUESTION AND ANSWER" in result["qa_block"]

    def test_empty_string(self):
        result = segment_transcript("")
        assert result["prepared_remarks"] == ""
        assert result["qa_block"] == ""

    def test_prepared_remarks_stripped_of_whitespace(self):
        text = "   Leading spaces.\n\nQ&A Session\nSomething"
        result = segment_transcript(text)
        assert not result["prepared_remarks"].startswith(" ")

    def test_hyphenated_question_and_answer(self):
        text = "Good quarter.\nQuestion-and-Answer\nAnalyst: Hi."
        result = segment_transcript(text)
        assert "Good quarter." in result["prepared_remarks"]
        assert "Question-and-Answer" in result["qa_block"]
