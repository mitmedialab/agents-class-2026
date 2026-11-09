"""Source-grounded comparison prompts for the deterministic weekly matcher."""

import re
from collections.abc import Mapping

from .models import Build
from .preview import evidence_passages, project_description
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


def _evidence(build: Build) -> tuple[set[str], set[str]]:
    summary = build.title + " " + project_description(build.content, build.title)
    prominent = set(re.findall(r"[a-z]+", summary.casefold()))
    body = " ".join(evidence_passages(build.content))
    return prominent, prominent | set(re.findall(r"[a-z]+", body.casefold()))


def pair_reason(
    mine: Build, peer: Build, shared: set[str], focus_hits: set[str], frequency: Mapping[str, int]
) -> str | None:
    my_summary, my_text = _evidence(mine)
    peer_summary, peer_text = _evidence(peer)

    # A method can transfer across topics. Require the method in the peer's own
    # project description and a place to apply it in the student's description.
    if {"multi", "agent"} <= peer_summary and peer_summary & {
        "creativity",
        "divergent",
        "ideation",
    }:
        method = (
            "The peer proposal brings several agents together to generate different perspectives."
        )
        if "museum" in my_summary and my_summary & {"companion", "guide", "visitor", "visitors"}:
            return (
                f"{method} In your museum guide, try offering two readings of the "
                "same artwork and let the visitor choose which one to explore."
            )
        if my_summary & {"brainstorming", "creativity", "ideation", "ideas"}:
            return (
                f"{method} Try having two agents suggest independent directions "
                "before your user chooses one."
            )

    matches = []
    for topic, keywords, prompt in _COMPARISONS:
        words = set(keywords.split())
        common = shared & my_text & peer_text & words
        personal = focus_hits & peer_text & words
        if common or personal:
            score = (
                bool(personal),
                bool(words & my_summary) + bool(words & peer_summary),
                sum(1 / frequency[t] for t in sorted(common | personal)),
            )
            if personal and not common:
                # Only the peer source and the saved focus support this subject.
                experiment = prompt.split(". ", 1)[-1]
                prompt = f"This peer project speaks to your saved focus on {topic}. {experiment}"
            matches.append((score, prompt))
    if matches:
        return max(matches, key=lambda match: match[0])[1]
    # Keep specific, student-supplied interests outside the comparison vocabulary
    # when the peer also names them in the title or introductory description.
    named_focus = (
        (focus_hits & peer_summary)
        - STOPWORDS
        - {"week", "final", "proposal", "using", "design", "prototype", "agent", "agents"}
    )
    if named_focus:
        term = min(named_focus, key=lambda word: (frequency[word], word))
        return (
            f"For your interest in “{term}”, try one example from this project with "
            "an input from your own build. Where does the approach still work?"
        )
    return None
