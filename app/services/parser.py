import re

# Ordered by specificity — first match wins.
_QA_BOUNDARY_PATTERNS = [
    r"question[\s\-]and[\s\-]answer session",
    r"q&a session",
    r"question and answer",
    r"question-and-answer",
    r"we will now begin the question",
    r"operator:\s*thank you",
]

_QA_RE = re.compile(
    "|".join(_QA_BOUNDARY_PATTERNS),
    re.IGNORECASE,
)


def segment_transcript(raw_text: str) -> dict:
    """Split raw transcript text into prepared remarks and Q&A block.

    Returns:
        {
            'prepared_remarks': str,
            'qa_block': str,
        }
    If no Q&A boundary is detected the entire text is treated as
    prepared_remarks and qa_block is an empty string.
    """
    match = _QA_RE.search(raw_text)
    if match:
        split_pos = match.start()
        return {
            "prepared_remarks": raw_text[:split_pos].strip(),
            "qa_block": raw_text[split_pos:].strip(),
        }
    return {
        "prepared_remarks": raw_text.strip(),
        "qa_block": "",
    }
