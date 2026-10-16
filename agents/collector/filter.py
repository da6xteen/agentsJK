import re
from typing import Tuple

RELEVANCE_KEYWORDS = [
    "строящ",
    "жк",
    "сдача",
    "котлован",
    "долевое",
    "новостройк",
    "квартир"
]

def check_relevance(text: str) -> Tuple[bool, str]:
    """
    Checks if text contains relevance keywords.
    Returns (is_relevant, reason).
    """
    if not text or not text.strip():
        return False, "Empty or missing text"

    text_lower = text.lower()
    matched = [kw for kw in RELEVANCE_KEYWORDS if kw in text_lower]

    if matched:
        return True, f"Matched relevance keywords: {', '.join(matched)}"
    else:
        return False, "No relevant keywords found in ad text"
