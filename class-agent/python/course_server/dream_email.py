"""Plain-text email rendering, separate from generation and mail delivery."""

from course_server.weekly_dreams import SavedDream


def email_subject(dream: SavedDream) -> str:
    return f"Your weekly dream · Week {dream.draft.week}"


def email_body(dream: SavedDream) -> str:
    """Render validated short content; transport supplies the trusted recipient."""
    paragraphs = [dream.draft.headline]
    for item in dream.draft.items:
        paragraphs.append(item.text + (f"\n{item.title}: {item.link}" if item.link else ""))
    return "\n\n".join(paragraphs)
