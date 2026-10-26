"""Curated closing quotes from AI and computing pioneers, rotated across issues."""

from __future__ import annotations

from collections.abc import Collection

from .models import PioneerQuote

PIONEER_QUOTES: tuple[PioneerQuote, ...] = (
    PioneerQuote(
        text=(
            "We can only see a short distance ahead, but we can see plenty there "
            "that needs to be done."
        ),
        author="Alan Turing",
        source="Computing Machinery and Intelligence, 1950",
    ),
    PioneerQuote(
        text=(
            "The hope is that, in not too many years, human brains and computing machines "
            "will be coupled together very tightly."
        ),
        author="J. C. R. Licklider",
        source="Man-Computer Symbiosis, 1960",
    ),
    PioneerQuote(
        text="You don't understand anything until you learn it more than one way.",
        author="Marvin Minsky",
        source="interview, 1980s",
    ),
    PioneerQuote(
        text="A wealth of information creates a poverty of attention.",
        author="Herbert A. Simon",
        source="Designing Organizations for an Information-Rich World, 1971",
    ),
    PioneerQuote(
        text="The best way to predict the future is to invent it.",
        author="Alan Kay",
        source="Xerox PARC, 1971",
    ),
    PioneerQuote(
        text=(
            "The Analytical Engine has no pretensions whatever to originate anything. "
            "It can do whatever we know how to order it to perform."
        ),
        author="Ada Lovelace",
        source="Notes on the Analytical Engine, 1843",
    ),
    PioneerQuote(
        text=(
            "Every aspect of learning or any other feature of intelligence can in principle "
            "be so precisely described that a machine can be made to simulate it."
        ),
        author="John McCarthy, Marvin Minsky, Nathaniel Rochester, and Claude Shannon",
        source="Dartmouth Summer Research Project proposal, 1955",
    ),
    PioneerQuote(
        text=("You can't think about thinking without thinking about thinking about something."),
        author="Seymour Papert",
        source="Mindstorms, 1980",
    ),
    PioneerQuote(
        text=(
            "The computer programmer is a creator of universes for which he alone is the lawgiver."
        ),
        author="Joseph Weizenbaum",
        source="Computer Power and Human Reason, 1976",
    ),
    PioneerQuote(
        text="The most dangerous phrase in the language is, 'We've always done it this way.'",
        author="Grace Hopper",
        source="interview, 1976",
    ),
    PioneerQuote(
        text=(
            "The world of the future will be an ever more demanding struggle against the "
            "limitations of our intelligence, not a comfortable hammock in which we can lie "
            "down to be waited upon by our robot slaves."
        ),
        author="Norbert Wiener",
        source="God & Golem, Inc., 1964",
    ),
    PioneerQuote(
        text=(
            "The digital revolution is far more significant than the invention of writing "
            "or even of printing."
        ),
        author="Douglas Engelbart",
        source="interview, 1990s",
    ),
)


def choose_quote(
    *,
    week_number: int,
    used_texts: Collection[str],
    quotes: tuple[PioneerQuote, ...] = PIONEER_QUOTES,
) -> PioneerQuote:
    """Rotate through the curated list by week, skipping quotes already sent."""

    if not quotes:
        raise ValueError("At least one quote is required")
    start = (week_number - 1) % len(quotes)
    for offset in range(len(quotes)):
        candidate = quotes[(start + offset) % len(quotes)]
        if candidate.text not in used_texts:
            return candidate
    return quotes[start]
