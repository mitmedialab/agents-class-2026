"""Explain a lexical weekly match using evidence available on its two cards."""

import re
from collections.abc import Mapping

from .models import Build
from .preview import evidence_passages, project_description
from .retrieval import STOPWORDS

# A comparison question is an invitation to inspect the work. Only show one
# when its subject occurs in readable project text and contributed to the match.
_COMPARISONS = (
    (
        "camera input",
        "camera cameras framing",
        "what each agent looks for in a frame before acting",
    ),
    (
        "light as a signal",
        "light lighting brightness",
        "when a change in light should prompt someone to act",
    ),
    (
        "voice interaction",
        "voice speech spoken",
        "how the user can interrupt or redirect the conversation",
    ),
    ("sensor input", "sensor sensors sensing", "how each prototype handles a noisy reading"),
    ("sound", "audio sound microphone", "which sounds should trigger a response"),
    (
        "memory",
        "memory recall retrieval saved",
        "what each system keeps and when it brings it back",
    ),
    (
        "idea generation",
        "ideation brainstorming creativity creative ideas alternatives",
        "how each interface helps someone explore a second idea",
    ),
    ("feedback", "feedback critique", "when feedback arrives and what the user can do with it"),
    ("images", "image images", "what visual information each system needs and how it uses it"),
    ("questions", "question questions", "how each agent chooses what to ask next"),
    ("agent actions", "actions acting", "what evidence each agent needs before its next move"),
    ("evaluation", "evaluation benchmark metrics", "what counts as a successful interaction"),
)


def pair_reason(
    mine: Build, peer: Build, shared: set[str], focus_hits: set[str], frequency: Mapping[str, int]
) -> tuple[str, str]:
    def evidence(build: Build) -> tuple[set[str], set[str]]:
        summary = build.title + " " + project_description(build.content, build.title)
        prominent = set(re.findall(r"[a-z]+", summary.casefold()))
        body = " ".join(evidence_passages(build.content))
        return prominent, prominent | set(re.findall(r"[a-z]+", body.casefold()))

    my_summary, my_text = evidence(mine)
    peer_summary, peer_text = evidence(peer)
    matches = []
    for topic, keywords, comparison in _COMPARISONS:
        words = set(keywords.split())
        common = shared & my_text & peer_text & words
        personal = focus_hits & peer_text & words
        if common or personal:
            score = (
                bool(personal),
                bool(words & my_summary) + bool(words & peer_summary),
                sum(1 / frequency[t] for t in sorted(common | personal)),
            )
            if personal:
                reason = f"The peer write-up matches your saved focus on {topic}."
            else:
                reason = f"Both write-ups discuss {topic}."
            matches.append((score, reason, comparison))
    if matches:
        _, reason, comparison = max(matches, key=lambda match: match[0])
        return reason, f"Compare {comparison}."

    # A specific title term can explain a match beyond the comparison topics above.
    title_words = set(re.findall(r"[a-z]+", f"{mine.title} {peer.title}".casefold()))
    terms = (shared & my_text & peer_text | focus_hits & peer_text) & title_words
    terms -= STOPWORDS | {"week", "final", "proposal", "prototype", "design", "building", "project"}
    if terms:
        term = min(terms, key=lambda word: (word not in focus_hits, frequency[word], word))
        if term in focus_hits:
            return f"The peer write-up mentions “{term}”, a term in your saved focus.", ""
        return f"Both projects mention “{term}” in their write-ups.", ""
    return (
        f"Both builds respond to the Week {mine.week} assignment.",
        "Compare the two approaches to the same brief.",
    )
