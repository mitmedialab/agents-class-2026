"""Lexical query expansion for English portfolio text, without routing chat intent."""

import re

# Common Chinese search terms expand to source vocabulary. These aliases are
# retrieval aids, never inferred student attributes or claims about a build.
ALIASES = {
    "硬件": "hardware electronics arduino sensor",
    "传感器": "sensor sensors",
    "记忆": "memory recall retrieval",
    "注意力": "attention focus distraction",
    "交互": "interaction interface feedback",
    "原型": "prototype prototyping",
    "评估": "evaluation benchmark testing",
    "学习": "learning learn",
    "创意": "creativity ideation creative",
    "设计": "design",
    "机械臂": "robot robotics arm",
    "语音": "voice speech audio",
    "反思": "reflection reflective",
}
STOPWORDS = set(
    [
        "the",
        "and",
        "for",
        "with",
        "how",
        "want",
        "project",
        "build",
        "this",
        "that",
        "help",
        "need",
        "learn",
        "learning",
        "struggling",
        "struggle",
        "currently",
        "current",
        "difficulty",
        "difficulties",
        "working",
        "work",
        "would",
        "like",
        "from",
        "have",
        "about",
        "someone",
        "students",
        "student",
        "peer",
        "peers",
    ]
)


def query_terms(text: str) -> set[str]:
    expanded = text.casefold()
    for label, words in ALIASES.items():
        if label in expanded:
            expanded += " " + words
    return set(re.findall(r"[a-z][a-z0-9-]{2,}", expanded)) - STOPWORDS
