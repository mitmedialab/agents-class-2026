"""Finds which builds and course materials resemble each other. Pure: no I/O or identity.

This is word overlap (TF-IDF cosine), not meaning. It needs no model or embedding provider, runs
the same way every time, and can name the words behind each score. The agent explains a connection
when a student asks it to.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from .models import ConnectionKind, TrailConnection

MAX_PER_KIND: dict[ConnectionKind, int] = {"build": 5, "class": 4, "classmate": 3}
MIN_SIMILARITY = 0.01
MAX_SHARED_TERMS = 5
MAX_DOCUMENT_CHARACTERS = 40_000
EXCERPT_CHARACTERS = 240

_WORD = re.compile(r"[a-z][a-z0-9-]{2,}|[一-鿿]+")
_STOPWORD_TEXT = """
    about above after again all also although always among and any are around because been before
    came come comes don doesn didn isn tell takes take little whole keeps keep say says saying
    being between both but can cannot could did does doing done down during each either enough even
    ever every few first for from further get gets getting going got had has have having her here
    hers him his how however into its just last later least less like made make makes making many
    may might more most much must near need needs never new next not now off often once one only
    onto other our ours out over own per put quite rather really said same second see seen she
    should since some still such than that the their theirs them then there these they thing things
    think this those three through thus time times too two under until upon use used uses using very
    want wanted was way ways week weeks well were what when where whether which while who whom whose
    why will with within without would yes yet you your yours
"""
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


@dataclass(frozen=True)
class ConnectionDocument:
    """Something that can be connected. `text` is only ever compared, never returned whole."""

    kind: ConnectionKind
    target_id: str
    title: str
    text: str
    week: int | None = None
    url: str | None = None
    owner_name: str | None = None


def _terms(text: str) -> list[str]:
    terms: list[str] = []
    for word in _WORD.findall(text.lower()):
        if word[0] < "一":
            if word not in _STOPWORDS:
                terms.append(word)
        else:
            # Chinese has no spaces, so overlapping character pairs stand in for words.
            terms.extend(word[index : index + 2] for index in range(len(word) - 1))
    return terms


def _weights(
    counts: Counter[str], document_frequency: Counter[str], total: int
) -> dict[str, float]:
    return {
        term: (1 + math.log(count)) * (0.1 + math.log((1 + total) / (1 + document_frequency[term])))
        for term, count in counts.items()
    }


def _excerpt(text: str, shared_terms: Sequence[str]) -> str:
    lowered = text.lower()
    positions = [lowered.find(term) for term in shared_terms]
    found = [position for position in positions if position >= 0]
    start = max(0, min(found) - EXCERPT_CHARACTERS // 3) if found else 0
    excerpt = " ".join(text[start : start + EXCERPT_CHARACTERS].split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + EXCERPT_CHARACTERS < len(text) else ""
    return f"{prefix}{excerpt}{suffix}"


def find_connections(
    source: ConnectionDocument, documents: Sequence[ConnectionDocument]
) -> list[TrailConnection]:
    """Rank `documents` against `source`, keeping the strongest few of each kind."""

    others = [document for document in documents if document.target_id != source.target_id]
    all_documents = [source, *others]
    counts = [
        Counter(
            _terms(f"{document.title} {document.title} {document.text[:MAX_DOCUMENT_CHARACTERS]}")
        )
        for document in all_documents
    ]
    document_frequency: Counter[str] = Counter()
    for count in counts:
        document_frequency.update(count.keys())
    weights = [_weights(count, document_frequency, len(all_documents)) for count in counts]
    norms = [math.sqrt(sum(value * value for value in weight.values())) for weight in weights]
    if norms[0] == 0:
        return []

    ranked: dict[ConnectionKind, list[TrailConnection]] = {kind: [] for kind in MAX_PER_KIND}
    for index, document in enumerate(others, start=1):
        if norms[index] == 0:
            continue
        overlap = {
            term: value * weights[index][term]
            for term, value in weights[0].items()
            if term in weights[index]
        }
        similarity = sum(overlap.values()) / (norms[0] * norms[index])
        if similarity < MIN_SIMILARITY:
            continue
        shared_terms = sorted(overlap, key=lambda term: (-overlap[term], term))[:MAX_SHARED_TERMS]
        ranked[document.kind].append(
            TrailConnection(
                kind=document.kind,
                target_id=document.target_id,
                title=document.title,
                week=document.week,
                url=document.url,
                owner_name=document.owner_name,
                excerpt=_excerpt(document.text, shared_terms),
                # Short notes have small raw values. The square root spreads them for reading.
                score=round(math.sqrt(similarity), 2),
                shared_terms=shared_terms,
            )
        )
    kept = [
        connection
        for kind, connections in ranked.items()
        for connection in sorted(connections, key=lambda item: -item.score)[: MAX_PER_KIND[kind]]
    ]
    return sorted(kept, key=lambda item: (-item.score, item.title))
