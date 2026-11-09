"""Source-grounded comparison prompts for the deterministic weekly matcher."""

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from math import sqrt

from .preview import project_description
from .retrieval import STOPWORDS

# Each prompt is a design experiment, not a claim about a peer's results.
_COMPARISONS = (
    (
        "camera input",
        "camera cameras framing",
        "Compare what each agent checks in a frame before acting. Try one of the "
        "peer project's checks on a frame your prototype misreads.",
    ),
    (
        "lighting",
        "light lighting brightness",
        "Look at when the peer project changes the light. Try using a single light "
        "cue at the moment someone needs to act in your prototype.",
    ),
    (
        "voice interaction",
        "voice speech spoken",
        "Compare how someone can interrupt each voice interaction. Try giving your "
        "user a way to pause and resume at the same point.",
    ),
    (
        "sensor input",
        "sensor sensors sensing",
        "Use a noisy reading from the peer project's sensor setup as a test case. "
        "What should your prototype do when it cannot trust an input?",
    ),
    (
        "sound",
        "audio sound microphone",
        "Compare which sounds each system treats as input. Try one background sound "
        "as a false-trigger test for your build.",
    ),
    (
        "memory",
        "memory recall retrieval saved",
        "Look at what the peer project saves and when it brings it back. Try "
        "retrieving one past interaction at a moment when it could change your "
        "user's next choice.",
    ),
    (
        "idea generation",
        "ideation brainstorming creativity creative ideas alternatives",
        "Look at how the peer project makes room for another idea. Try giving your "
        "user a second direction to explore before they commit to the first.",
    ),
    (
        "feedback",
        "feedback critique",
        "Compare when feedback reaches the user. Try moving one suggestion earlier "
        "in your interaction, while the user can still act on it.",
    ),
    (
        "images",
        "image images",
        "Compare what information each project takes from an image. Try removing "
        "one visual cue and see whether your build still makes a useful suggestion.",
    ),
    (
        "questions",
        "question questions",
        "Compare how the two agents choose a follow-up question. Try changing your "
        "agent's next question based on the user's last answer.",
    ),
    (
        "agent actions",
        "actions acting",
        "Compare what each agent observes before it acts. Try giving yours one "
        "condition under which it should pause and ask the user.",
    ),
    (
        "evaluation",
        "evaluation benchmark metrics",
        "Look at what counts as success in the peer evaluation. Try that criterion "
        "on one case where your own build seemed to work.",
    ),
)


_COMMON_WORDS = (
    "week weekly final assignment course prototype design system tool tools interface "
    "project projects build builds agent agents using used use uses make made making "
    "which when then them they there their also each only through after before some "
    "what into here able these those been will first next than most other another "
    "based same different scratch minimal version proposal cognitive augmentation "
    "should could action actions simple include class user users people someone "
    "input output makes making today work works working more data process model "
    "approach goal task loop specific provides allows lets designed instead without between "
    "within always where whether might those still every source public various coursework "
    "semester implement implementation implemented built environment environments evaluated "
    "evaluating evaluation evaluate human example examples actual following looking effort "
    "testing test tests results outcome main challenge trying create created given available "
    "will well part detail key includes into document write code tool tools claude codex "
    "through across learn end check takes one two both while way possible since out down "
    "does has had you your its can our was were him her his she who all day not are but "
    "helpful enough think something current better content"
)
_COMMON = STOPWORDS | set(_COMMON_WORDS.split())

# Standalone words need to name an identifiable subject. Distinctive phrases
# and confirmed interests remain open-vocabulary.
_SUBJECT_WORDS = (
    "canvas drawing knitting weaving robotics embroidery sculpture museum navigation "
    "recall retrieval sensor lighting microphone framing camera speech audio animation "
    "storytelling calibration reflection memory brainstorming ideation dialogue "
    "typography haptics gestures positioning fabrication mapping"
)
_SUBJECTS = set(_SUBJECT_WORDS.split())
_ADMIN = re.compile(
    r"\b(?:skip to content|all weeks|presented in class|course website|"
    r"for this assignment you|you (?:must|should) submit|grading rubric|"
    r"this week.s assignment|build an agent (?:from scratch|that can)|design and build an "
    r"environment|due (?:mon|tues)day|pull request|ai disclosure|claude code|"
    r"used (?:claude|codex|chatgpt|copilot)|as per the assignment|grading criteria)\b",
    re.I,
)
_SKIP_SECTION = re.compile(
    r"^(?:references?|citations?|bibliography|related work|assignment brief|"
    r"research papers?|resources|prior work|"
    r"ai (?:use|disclosure|assistance)|credits?|course requirements)\b",
    re.I,
)


def terms(text: str) -> set[str]:
    words = list(re.finditer(r"[a-z]+(?:-[a-z]+)*", text.lower()))
    result = {m[0] for m in words if len(m[0]) >= 3 and m[0] not in _COMMON}
    for left, right in pairwise(words):
        if left[0] in result and right[0] in result and text[left.end() : right.start()].isspace():
            result.add(f"{left[0]} {right[0]}")

    for topic, keywords, _ in _COMPARISONS:
        if not result.isdisjoint(keywords.split()):
            result.add("~" + topic)
    return result


@dataclass
class Profile:
    prominent: set[str]
    vocabulary: set[str]
    passages: list[tuple[str, set[str]]]
    locations: dict[str, list[int]]


@lru_cache(maxsize=256)
def build_profile(title: str, content: str) -> Profile:
    """Use only the public build text. Personal interests never enter this cache."""
    lines = content.splitlines()
    passages: dict[str, set[str]] = {}
    skip = False
    fenced = False
    for index, line in enumerate(lines):
        line = line.strip()
        if line.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or not line:
            continue
        if line.startswith("#") or (
            index + 1 < len(lines) and re.fullmatch(r"[-=]{3,}", lines[index + 1].strip())
        ):
            skip = bool(_SKIP_SECTION.match(line.strip("# ")))
            continue
        if skip or _ADMIN.search(line) or line.count("](") > 1:
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line).strip(" *-")
        line = line.replace("**", "")
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if not 6 <= len(sentence.split()) <= 36 or re.search(
                r"https?://|[|`{}<>\[\]]", sentence
            ):
                continue
            words = terms(sentence)
            if len(words) >= 2:
                passages[sentence] = words
    # Imported snapshots sometimes end mid-sentence. They still carry topic
    # evidence but their cut-off text should never be quoted to a student.
    intro = project_description(content, title) or next(iter(passages), "")
    prominent = terms(title) | terms(intro)
    vocabulary = prominent.union(*passages.values())
    locations: dict[str, list[int]] = {}
    for index, words in enumerate(passages.values()):
        for word in words:
            locations.setdefault(word, []).append(index)
    return Profile(prominent, vocabulary, list(passages.items()), locations)


def match_builds(
    mine: Profile, peer: Profile, focus: set[str], frequency: Counter[str]
) -> tuple[float, str] | None:
    if not mine.passages or not peer.passages:
        return None
    shared = mine.vocabulary & peer.vocabulary
    personal = focus & peer.vocabulary

    def weight(term: str) -> float:
        return (2 if " " in term else 1) / sqrt(max(1, frequency[term]))

    # Accumulate overlap only within an actual pair of passages. A long write-up
    # cannot combine disconnected mentions from its introduction and references.
    weights = {t: weight(t) * (1 + (t in mine.prominent) + (t in peer.prominent)) for t in shared}
    best_score = 0.0
    best_reason = ""
    for sentence, words in peer.passages:
        relevant = words & (shared | personal)
        if not relevant:
            continue
        overlaps: dict[int, list[str]] = {}
        for term in sorted(relevant & shared):
            for index in mine.locations.get(term, []):
                overlaps.setdefault(index, []).append(term)
        personal_hits = words & personal
        focus_score = sum(sorted((weight(t) for t in personal_hits), reverse=True)[:2]) * 3
        if overlaps:

            def passage_score(hits: list[str]) -> float:
                return sum(sorted((weights[t] for t in hits), reverse=True)[:4])

            index, hits = max(overlaps.items(), key=lambda item: passage_score(item[1]))
            common = set(hits)
            score = passage_score(hits) + focus_score
        else:
            index, common, score = -1, set(), focus_score
        if score <= best_score:
            continue
        reason = ""
        anchors = {
            t
            for t in common
            if " " in t and not t.startswith("~") and (t in mine.prominent or t in peer.prominent)
        }
        anchors = anchors or {t for t in common & mine.prominent & peer.prominent if t in _SUBJECTS}
        if personal_hits and not common:
            anchors = {
                t for t in personal_hits & peer.prominent if len(t) >= 4 and not t.startswith("~")
            }
        if (
            anchors
            and sentence[:1].isupper()
            and sentence.endswith(".")
            and len(sentence) <= 170
            and (index < 0 or mine.passages[index][0] != sentence)
        ):
            key = min(anchors, key=lambda t: (frequency[t], t))
            if key in personal_hits and key not in common:
                reason = (
                    f"For your saved focus on {key}, consider the peer's approach: “{sentence}”"
                )
            else:
                reason = f"For your work on {key}, try the peer's approach: “{sentence}”"
        # Require evidence of the topic in a source passage, independently on both sides.
        matches = []
        for topic, keywords, prompt in _COMPARISONS:
            keys = set(keywords.split())
            topic_terms = keys & words
            if not topic_terms or not ("~" + topic in common or "~" + topic in focus):
                continue
            strength = max(weight(t) for t in topic_terms)
            if "~" + topic in focus and "~" + topic not in common:
                experiment = prompt.split(". ", 1)[-1]
                prompt = f"This peer project speaks to your saved focus on {topic}. {experiment}"
            if (
                not reason
                and "~" + topic not in focus
                and sentence[:1].isupper()
                and sentence.endswith(".")
                and len(sentence) <= 150
                and index >= 0
                and mine.passages[index][0] != sentence
                and not re.search(r"\b(?:assignment|the course|the brief)\b", sentence, re.I)
            ):
                suggestion = prompt.split(". ", 1)[-1]
                prompt = f"On {topic}, the peer writes: “{sentence}” {suggestion}"
            matches.append((strength, prompt))
        if matches and (not reason or (personal_hits and not common)):
            reason = max(matches, key=lambda m: m[0])[1]
        if reason:
            best_score, best_reason = score, reason

    if best_reason:
        return best_score, best_reason

    # Transfer a documented divergence technique to a project that explicitly
    # supports interpretation or exploration, even without literal word overlap.
    if {"multi-agent", "creativity"} <= peer.prominent and mine.prominent & {
        "interpretation",
        "interpretations",
        "discuss",
        "brainstorming",
        "ideation",
    }:
        return 0.25, (
            "The peer proposal uses several agents to generate different perspectives. "
            "Try offering two interpretations and letting your user choose which to explore."
        )
    return None
