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


def email_html(dream: SavedDream, *, demo: bool = False) -> str:
    """Simple email-safe HTML using the same validated content as plain-text mail."""
    from html import escape

    paragraphs = []
    for item in dream.draft.items:
        link = (
            ' <a style="color:#111;text-decoration:underline" href="'
            + escape(item.link, quote=True)
            + '">'
            + escape(item.title)
            + "</a>"
            if item.link and item.link.startswith("https://")
            else ""
        )
        paragraphs.append('<p style="margin:18px 0">' + escape(item.text) + link + "</p>")
    notice = (
        '<p style="font-size:12px;color:#777;border-top:1px solid #ddd;padding-top:16px">'
        "Demo email · prepared with Codex and validated locally. "
        "Automatic Course Agent delivery is not connected.</p>"
        if demo
        else ""
    )
    return (
        '<div style="background:#fff;color:#111;max-width:600px;margin:24px auto;'
        'font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:1.6;padding:24px">'
        '<p style="font-size:12px;color:#777;margin:0 0 24px">WEEKLY DREAM · FOR BROOKE</p>'
        '<h2 style="font-size:24px;line-height:1.3;font-weight:500;margin:0 0 24px">'
        + escape(dream.draft.headline)
        + "</h2>"
        + "".join(paragraphs)
        + notice
        + "</div>"
    )
