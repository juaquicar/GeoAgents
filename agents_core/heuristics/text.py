import re
import unicodedata
from typing import List


STOPWORDS = {
    "a",
    "al",
    "and",
    "con",
    "de",
    "del",
    "el",
    "en",
    "esta",
    "este",
    "for",
    "la",
    "las",
    "los",
    "mapa",
    "por",
    "que",
    "quiero",
    "sobre",
    "the",
    "un",
    "una",
    "ver",
    "zona",
}


def strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(ch)
    )


def normalize_goal(goal: str) -> str:
    cleaned = strip_accents((goal or "").lower())
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def goal_keywords(goal: str, limit: int = 8) -> List[str]:
    tokens = []
    seen = set()

    for token in normalize_goal(goal).split():
        if len(token) <= 2 or token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= limit:
            break

    return tokens


def build_goal_signature(goal: str) -> str:
    keywords = goal_keywords(goal, limit=6)
    return "|".join(keywords) if keywords else "generic"