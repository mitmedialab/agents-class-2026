"""Deterministic plain-text and HTML renderings of a newsletter issue.

The HTML follows the course site's visual language: a black ground, ivory display text,
quiet sentence-case labels, near-white secondary text, and fine rules. Every string
that originated in the model or in repository metadata is escaped here, and only roster URLs
resolved by platform code become links.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta
from html import escape
from urllib.parse import urlencode, urlsplit

from .models import HighlightImage, NewsletterIssue, ProjectLink

_MARKDOWN_LINK = re.compile(r"\[([^\]\n]{1,120})\]\((https://[^\s)]+)\)")

_RULE = "-" * 60
# The selection line opens the course site with this as the student's first question to the
# Course Agent (apps/web/src/startupQuery.ts reads `q`), which answers from the course FAQ.
HIGHLIGHTS_QUESTION = "newslettercriteria"

# Mirrors packages/ui/src/styles.css tokens; email clients need literal values.
_GROUND = "#000000"
_SURFACE = "#111111"
_INK = "#f5f5f2"
# Secondary text is near-white on purpose: the site's muted grey reads as a watermark in an
# inbox, so the email separates levels by size and weight rather than by dimming the text.
_INK_SOFT = "#f0f0ec"
_MUTED = "#d6d6d0"
_BORDER = "#2a2a28"
_SANS = "'Helvetica Neue',Helvetica,Arial,sans-serif"
# Section labels and metadata: the body face in sentence case, small and medium-weight.
_LABEL = f"font-family:{_SANS};font-size:14px;line-height:1.4;font-weight:500;color:{_MUTED};"
_SECTION = f"font-family:{_SANS};font-size:15px;line-height:1.4;font-weight:600;color:{_INK};"
# Section subheadings sit between the 17px body and the 34px headline, bold so they read as
# headings, and small enough that "All the other builds this week" fits a phone's width.
_SUBHEAD = (
    f"font-family:{_SANS};font-size:22px;line-height:1.25;font-weight:700;"
    f"letter-spacing:-0.01em;color:{_INK};"
)
# An approach heading over a few names in the list of other builds: one step up from the
# names, well under the section subheading.
_GROUP_HEADING = f"font-family:{_SANS};font-size:17px;line-height:1.3;font-weight:600;color:{_INK};"
_BODY = f"font-family:{_SANS};font-size:16px;line-height:1.55;color:{_INK_SOFT};"
# Other builds the editorial placed under no approach are listed last under this heading.
UNGROUPED_HEADING = "Other paths"
ASK_AROUND_LABEL = "Who got past it"
# Link underlines sit inside the text blend below, where a client that recolors borders and one
# that does not produce mirror-image results; a mid grey looks the same either way.
_LINK_LINE = "#7d7d78"
_UNDERLINED = (
    f"color:{_INK};text-decoration:none;border-bottom:1px solid {_LINK_LINE};padding-bottom:3px;"
)

# The Gmail apps recolor dark emails in dark mode: plain backgrounds turn light and light text
# turns grey, while gradient backgrounds are left alone. Every run of text therefore sits inside
# a screen/difference blend pair (Rémi Parmentier's technique). It cancels Gmail's recoloring
# and composites to the original pixels in every other client. The styles must be inline: the
# Gmail iPhone app ignored the same rules when they came from a stylesheet. Images and rules
# stay outside the pair, because a difference blend would invert them.
_TEXT_OPEN = (
    '<div style="background:#000;mix-blend-mode:screen;">'
    '<div style="background:#000;mix-blend-mode:difference;">'
)
_TEXT_CLOSE = "</div></div>"
# WebKit's per-element opt-out from the color filter Mac Mail applies to adapt a message.
_APPLE_FILTER_OFF = "html,body,*{-apple-color-filter:none !important;}"
# Section rules are painted as gradients, which Gmail's dark mode leaves alone.
_SECTION_RULE = (
    '<div style="margin:36px 0;height:1px;line-height:1px;font-size:1px;'
    f"mso-line-height-rule:exactly;background-color:{_BORDER};"
    f'background-image:linear-gradient({_BORDER},{_BORDER});">&nbsp;</div>'
)

ImageSource = Callable[[HighlightImage], str]


def _text_block(inner: str) -> str:
    """Wrap a run of text-only markup so Gmail's dark mode cannot dim it."""

    return f"{_TEXT_OPEN}{inner}{_TEXT_CLOSE}"


def _short_date(value: date) -> str:
    return f"{value.strftime('%b')} {value.day}"


def window_label(issue: NewsletterIssue) -> str:
    week = issue.week
    last_day = (week.ends_at - timedelta(days=1)).date()
    return (
        f"Week {week.number} · {_short_date(week.class_date)} \u2013 {_short_date(last_day)}, "
        f"{last_day.year}"
    )


def _course_line(issue: NewsletterIssue) -> str:
    branding = issue.branding
    return (
        f"{branding.course_code} · {branding.course_title} · "
        f"{branding.institution}, {branding.course_term}"
    )


def highlights_question_url(issue: NewsletterIssue) -> str:
    site = issue.branding.course_site_url.rstrip("/")
    return f"{site}/?{urlencode({'q': HIGHLIGHTS_QUESTION})}"


def _in_sentence(name: str) -> str:
    """'The MAS.S60 teaching team' reads as 'the MAS.S60 teaching team' mid-sentence."""

    return f"the {name[4:]}" if name.startswith("The ") else name


def _selection_line(issue: NewsletterIssue) -> str:
    return f"How {_in_sentence(issue.branding.editor_name)} chooses what to highlight"


def _site_label(url: str) -> str:
    parts = urlsplit(url)
    return (parts.netloc + parts.path).rstrip("/") or url


def _project_line(issue: NewsletterIssue, link: ProjectLink) -> str:
    built = issue.built_for(link.project_id) or "Nothing posted for this week yet."
    site = f" {link.post_url or link.site_url}" if (link.post_url or link.site_url) else ""
    return f"{link.label}: {built}{site}"


def _named(issue: NewsletterIssue, project_id: str) -> tuple[str, str | None]:
    link = issue.link_for(project_id)
    return (link.label if link else project_id, issue.open_url(project_id))


def _ask_around_text(issue: NewsletterIssue) -> list[str]:
    if not issue.body.ask_around:
        return []
    lines = ["", ASK_AROUND_LABEL.upper()]
    for entry in issue.body.ask_around:
        people = [
            f"{label} ({url})" if url else label
            for label, url in (_named(issue, project_id) for project_id in entry.project_ids)
        ]
        lines.append(f"- {entry.question} Ask {' or '.join(people)}.")
    return lines


def _other_builds_text(issue: NewsletterIssue) -> list[str]:
    sections = issue.grouped_other_projects()
    if not sections:
        return ["- Everyone who posted made the highlights this week."]
    lines: list[str] = []
    for heading, links in sections:
        if heading is not None or len(sections) > 1:
            lines.extend(["", heading or UNGROUPED_HEADING])
        lines.extend(f"- {_project_line(issue, link)}" for link in links)
    return lines


def render_text(issue: NewsletterIssue) -> str:
    branding = issue.branding
    lines: list[str] = [
        f"{branding.newsletter_name.upper()} · ISSUE {issue.week.number:02d}",
        issue.body.headline,
        "",
        window_label(issue),
        f"THE ASSIGNMENT: {issue.week.tutorial}",
        "",
        _MARKDOWN_LINK.sub(r"\1 (\2)", issue.body.editorial),
        "",
        f"— {branding.editor_name}",
        *_ask_around_text(issue),
        "",
        _RULE,
        "",
        "HIGHLIGHTS*",
        "",
    ]
    for index, highlight in enumerate(issue.body.highlights, start=1):
        link = issue.link_for(highlight.project_id)
        label = link.label if link else highlight.project_id
        lines.append(f"{index}. {highlight.headline} — {label}")
        lines.append(f"   {highlight.description}")
        if link and (link.post_url or link.site_url):
            lines.append(f"   Open it: {link.post_url or link.site_url}")
        lines.append("")
    lines.append(f"* {_selection_line(issue)}: {highlights_question_url(issue)}")
    lines.append("")
    lines.append("ALL THE OTHER BUILDS THIS WEEK")
    lines.extend(_other_builds_text(issue))
    lines.extend(
        [
            "",
            _RULE,
            f'"{issue.quote.text}"',
            f"— {issue.quote.author}, {issue.quote.source}"
            + (f" ({issue.quote.url})" if issue.quote.url else ""),
            "",
            f"This newsletter was created by {branding.editor_name}.",
            "",
            _course_line(issue),
            f"Class website: {branding.course_site_url}",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def relative_image_source(issue: NewsletterIssue) -> ImageSource:
    """Image paths for the on-disk preview that sits next to the issue's asset folder."""

    return lambda image: f"{issue.issue_id}/{image.filename}"


def cid_image_source(image: HighlightImage) -> str:
    """Image references for an email whose images travel as inline attachments."""

    return f"cid:{image.content_id}"


def _anchor(url: str, inner: str, *, style: str) -> str:
    return f'<a href="{escape(url, quote=True)}" style="{style}">{inner}</a>'


def _prose_html(text: str) -> str:
    """Escape prose, turning only validated Markdown links into anchors."""

    parts: list[str] = []
    position = 0
    for match in _MARKDOWN_LINK.finditer(text):
        parts.append(escape(text[position : match.start()]))
        parts.append(_anchor(match.group(2), escape(match.group(1)), style=_UNDERLINED))
        position = match.end()
    parts.append(escape(text[position:]))
    return "".join(parts)


def _highlight_html(issue: NewsletterIssue, index: int, *, image_src: ImageSource) -> str:
    highlight = issue.body.highlights[index - 1]
    link = issue.link_for(highlight.project_id)
    label = escape(link.label if link else highlight.project_id)
    site_url = (link.post_url or link.site_url) if link else None
    image = issue.image_for(highlight.project_id)
    figure = ""
    if image is not None:
        img = (
            f'<img src="{escape(image_src(image), quote=True)}" width="600" '
            f'alt="{escape(highlight.headline, quote=True)}" '
            f'style="display:block;width:100%;max-width:600px;height:auto;border:1px solid '
            f'{_BORDER};border-radius:12px;background:{_SURFACE};">'
        )
        framed = _anchor(site_url, img, style="text-decoration:none;") if site_url else img
        figure = f'<div style="margin:0 0 18px 0;">{framed}</div>'
    open_link = (
        '<p style="margin:14px 0 0 0;">'
        + _anchor(site_url, f"Open {label}&rsquo;s build &rarr;", style=f"{_LABEL}{_UNDERLINED}")
        + "</p>"
        if site_url
        else ""
    )
    text = _text_block(
        f'<p style="margin:0 0 8px 0;{_LABEL}">{index:02d} &middot; {label}</p>'
        f'<h2 style="margin:0 0 10px 0;font-family:{_SANS};font-size:24px;line-height:1.2;'
        f'font-weight:500;color:{_INK};">{escape(highlight.headline)}</h2>'
        f'<p style="margin:0;font-family:{_SANS};font-size:16px;line-height:1.55;'
        f'color:{_INK_SOFT};">{escape(highlight.description)}</p>'
        f"{open_link}"
    )
    return f'<div style="margin:0 0 48px 0;">{figure}{text}</div>'


def _other_build_html(issue: NewsletterIssue, link: ProjectLink) -> str:
    # Names that link read as links: the same mid-grey underline as every other link.
    name_style = f"{_LABEL}font-weight:600;{_UNDERLINED}"
    return (
        '<p style="margin:0 0 12px 0;">'
        + (
            _anchor(link.post_url or link.site_url or "", escape(link.label), style=name_style)
            if (link.post_url or link.site_url)
            else f'<span style="{_LABEL}font-weight:600;color:{_INK};">{escape(link.label)}</span>'
        )
        # A little air under the underlined name; clients without inline-block just wrap.
        + f'<br><span style="display:inline-block;margin-top:5px;font-family:{_SANS};'
        f'font-size:15px;line-height:1.5;color:{_INK_SOFT};">'
        + escape(issue.built_for(link.project_id) or "Nothing posted for this week yet.")
        + "</span></p>"
    )


def _other_builds_html(issue: NewsletterIssue) -> str:
    """The other builds, under their approach headings when the editorial grouped them."""

    sections = issue.grouped_other_projects()
    if not sections:
        return (
            f'<p style="margin:0;{_LABEL}">Everyone who posted made the highlights this week.</p>'
        )
    parts: list[str] = []
    for position, (heading, links) in enumerate(sections):
        if heading is not None or len(sections) > 1:
            top = "0" if position == 0 else "26px"
            parts.append(
                f'<p style="margin:{top} 0 14px 0;{_GROUP_HEADING}">'
                f"{escape(heading or UNGROUPED_HEADING)}</p>"
            )
        parts.extend(_other_build_html(issue, link) for link in links)
    return "".join(parts)


def _ask_around_html(issue: NewsletterIssue) -> str:
    """Under the editorial: each blocker it named, and the classmates who got past it."""

    if not issue.body.ask_around:
        return ""
    rows: list[str] = []
    for entry in issue.body.ask_around:
        people: list[str] = []
        for project_id in entry.project_ids:
            label, url = _named(issue, project_id)
            people.append(
                _anchor(url, escape(label), style=f"font-weight:600;{_UNDERLINED}")
                if url
                else f'<span style="font-weight:600;">{escape(label)}</span>'
            )
        rows.append(
            f'<p style="margin:0 0 10px 0;{_BODY}">{escape(entry.question)} Ask '
            f"{' or '.join(people)}.</p>"
        )
    return (
        f'<p style="margin:30px 0 10px 0;{_SECTION}color:{_MUTED};">{ASK_AROUND_LABEL}</p>'
        + "".join(rows)
    )


def render_html(
    issue: NewsletterIssue,
    *,
    image_src: ImageSource | None = None,
    logo_src: str | None = None,
) -> str:
    branding = issue.branding
    source = image_src or relative_image_source(issue)
    highlights = "".join(
        _highlight_html(issue, index, image_src=source)
        for index in range(1, len(issue.body.highlights) + 1)
    )
    other_names = _other_builds_html(issue)
    editorial = "".join(
        f'<p style="margin:0 0 18px 0;font-family:{_SANS};font-size:17px;line-height:1.65;'
        f'color:{_INK_SOFT};">{_prose_html(paragraph.strip())}</p>'
        for paragraph in re.split(r"\n\s*\n|\n", issue.body.editorial)
        if paragraph.strip()
    )
    attribution = f"&mdash; {escape(issue.quote.author)}, {escape(issue.quote.source)}"
    if issue.quote.url:
        attribution = _anchor(issue.quote.url, attribution, style=f"{_LABEL}text-decoration:none;")
    rule = _SECTION_RULE
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        # Mac Mail recolors a message with its own color filter to match its light or dark
        # setting, which turned the white text dark. Two guards, each enough on its own in
        # testing: declaring support for both schemes, and switching the filter off.
        '<meta name="color-scheme" content="light dark">'
        '<meta name="supported-color-schemes" content="light dark">'
        # Mail clients that honor a stylesheet get the scheme and a black ground; the inline
        # bgcolor attributes below carry the ground for the ones that strip <style>.
        f"<style>:root{{color-scheme:light dark;}}body,table,td{{background-color:{_GROUND};}}"
        f"a{{color:{_INK};}}{_APPLE_FILTER_OFF}</style>"
        f"<title>{escape(issue.subject)}</title></head>"
        f'<body bgcolor="{_GROUND}" style="-apple-color-filter:none;margin:0;padding:0;'
        f'background-color:{_GROUND};color:{_INK};">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{_GROUND}" style="background-color:{_GROUND};"><tr>'
        # The flat gradient is deliberate: Gmail's app-side dark mode inverts plain background
        # colors on dark emails but leaves gradient backgrounds alone.
        f'<td align="center" bgcolor="{_GROUND}" style="padding:40px 16px;'
        f'background-color:{_GROUND};background-image:linear-gradient({_GROUND},{_GROUND});">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{_GROUND}" style="max-width:600px;width:100%;background-color:{_GROUND};">'
        f'<tr><td bgcolor="{_GROUND}" style="text-align:left;background-color:{_GROUND};'
        f'background-image:linear-gradient({_GROUND},{_GROUND});color:{_INK};">'
        + (
            f'<img src="{escape(logo_src, quote=True)}" width="600" '
            f'alt="{escape(branding.newsletter_name)}" style="display:block;width:100%;'
            'max-width:600px;height:auto;margin:0 0 22px 0;">'
            if logo_src
            else ""
        )
        + _TEXT_OPEN
        + (
            f'<p style="margin:0 0 28px 0;{_LABEL}">Issue {issue.week.number:02d}</p>'
            if logo_src
            else f'<p style="margin:0 0 28px 0;{_LABEL}">{escape(branding.newsletter_name)} '
            f"&middot; Issue {issue.week.number:02d}</p>"
        )
        + f'<h1 style="margin:0 0 24px 0;font-family:{_SANS};font-size:34px;line-height:1.15;'
        f'font-weight:500;letter-spacing:-0.01em;color:{_INK};">{escape(issue.body.headline)}</h1>'
        f'<p style="margin:0 0 10px 0;{_LABEL}">{escape(window_label(issue))}</p>'
        # The assignment is context for the issue, so it sits one step greyer than the headline.
        f'<p style="margin:0 0 6px 0;{_SECTION}color:{_MUTED};">The assignment</p>'
        f'<p style="margin:0 0 28px 0;font-family:{_SANS};font-size:20px;line-height:1.4;'
        f'font-weight:400;color:{_MUTED};">{escape(issue.week.tutorial)}</p>'
        f'<p style="margin:0 0 14px 0;{_SUBHEAD}">How the week went</p>'
        f"{editorial}"
        f'<p style="margin:-6px 0 0 0;{_LABEL}">&mdash; {escape(branding.editor_name)}</p>'
        f"{_ask_around_html(issue)}"
        f"{_TEXT_CLOSE}{rule}{_TEXT_OPEN}"
        f'<p style="margin:0 0 24px 0;{_SUBHEAD}">Highlights*</p>'
        f"{_TEXT_CLOSE}"
        f"{highlights}"
        # A footnote to the whole section, marked like the heading and set apart from the
        # last highlight, so it cannot read as that build's link.
        + _text_block(
            f'<p style="margin:0;{_LABEL}">*&nbsp;'
            + _anchor(
                highlights_question_url(issue),
                f"{escape(_selection_line(issue))} &rarr;",
                style=f"{_LABEL}{_UNDERLINED}color:{_MUTED};",
            )
            + "</p>"
        )
        + f"{rule}{_TEXT_OPEN}"
        f'<p style="margin:0 0 18px 0;{_SUBHEAD}">All the other builds this week</p>'
        f"{other_names}"
        f"{_TEXT_CLOSE}{rule}{_TEXT_OPEN}"
        f'<p style="margin:0 0 12px 0;font-family:{_SANS};font-size:21px;line-height:1.4;'
        f'font-weight:300;color:{_INK};">&ldquo;{escape(issue.quote.text)}&rdquo;</p>'
        f'<p style="margin:0;{_LABEL}">{attribution}</p>'
        f"{_TEXT_CLOSE}{rule}{_TEXT_OPEN}"
        # Colophon order: who made this issue, then whose course it is and where to find it.
        f'<p style="margin:0 0 26px 0;{_LABEL}">This newsletter was created by '
        f"{escape(branding.editor_name)}</p>"
        f'<p style="margin:0 0 10px 0;{_LABEL}">{escape(_course_line(issue))}</p>'
        '<p style="margin:0;">'
        + _anchor(
            branding.course_site_url,
            escape(_site_label(branding.course_site_url)),
            style=f"{_LABEL}{_UNDERLINED}",
        )
        + "</p>"
        f"{_TEXT_CLOSE}"
        "</td></tr></table></td></tr></table></body></html>\n"
    )


# --- Markdown -------------------------------------------------------------------------------
#
# The Markdown rendering is what the course site's Newsletters pages and the Course Agent read:
# one issue as a course resource. Highlight images are referenced by their registered asset id
# (the project id); the site resolves ids through the authorized asset route and the agent sees
# the same ids as the resource's registered assets.

_MD_INLINE_SPECIALS = re.compile(r"[\\*_`\[\]<~]")
_MD_BLOCK_STARTS = re.compile(r"^(\s*)([#>|+-]|\d+[.)](?=\s))")
_MD_URL_UNSAFE = {" ": "%20", "(": "%28", ")": "%29"}


_ASSET_ID_UNSAFE = re.compile(r"[^a-z0-9]+")


def image_asset_id(image: HighlightImage) -> str:
    """The registered asset id of a highlight image, in the catalog's asset-id form.

    Asset ids are lowercase letters, digits, and underscores, so the project id is folded into
    that form: `agents2026-ada` becomes `agents2026_ada`.
    """

    normalized = _ASSET_ID_UNSAFE.sub("_", image.project_id.casefold()).strip("_")
    return normalized if normalized[:1].isalpha() else f"p_{normalized}"


def asset_image_source(image: HighlightImage) -> str:
    """Image references for Markdown served as a course resource: the registered asset id."""

    return image_asset_id(image)


def _md_text(text: str) -> str:
    """Escape prose so no model- or repository-supplied string becomes Markdown structure."""

    escaped = _MD_INLINE_SPECIALS.sub(lambda match: "\\" + match.group(0), text)
    return "\n".join(_MD_BLOCK_STARTS.sub(r"\1\\\2", line) for line in escaped.splitlines())


def _md_url(url: str) -> str:
    return "".join(_MD_URL_UNSAFE.get(character, character) for character in url)


def _md_link(label: str, url: str) -> str:
    return f"[{_md_text(label)}]({_md_url(url)})"


def _md_prose(text: str) -> str:
    """Escape prose while keeping its validated Markdown links as links."""

    parts: list[str] = []
    position = 0
    for match in _MARKDOWN_LINK.finditer(text):
        parts.append(_md_text(text[position : match.start()]))
        parts.append(_md_link(match.group(1), match.group(2)))
        position = match.end()
    parts.append(_md_text(text[position:]))
    return "".join(parts)


def _md_highlight(issue: NewsletterIssue, index: int, *, image_src: ImageSource) -> list[str]:
    highlight = issue.body.highlights[index - 1]
    link = issue.link_for(highlight.project_id)
    label = link.label if link else highlight.project_id
    site_url = (link.post_url or link.site_url) if link else None
    image = issue.image_for(highlight.project_id)
    lines = [f"### {_md_text(highlight.headline)}", "", f"{index:02d} · {_md_text(label)}", ""]
    if image is not None:
        figure = f"![{_md_text(highlight.headline)}]({_md_url(image_src(image))})"
        lines.extend([f"[{figure}]({_md_url(site_url)})" if site_url else figure, ""])
    lines.extend([_md_text(highlight.description), ""])
    if site_url:
        lines.extend([_md_link(f"Open {label}\u2019s build \u2192", site_url), ""])
    return lines


def masthead_markdown(name: str, logo_src: str) -> str:
    """The wordmark as the first block of a page, before its title."""

    return f"![{_md_text(name)}]({_md_url(logo_src)})"


def render_markdown(
    issue: NewsletterIssue,
    *,
    image_src: ImageSource | None = None,
    index_uri: str | None = None,
    logo_src: str | None = None,
) -> str:
    """The issue as Markdown: the same sections as the email, links active, images by asset id.

    `index_uri` adds a closing link back to the list of every issue; `logo_src` puts the
    wordmark above the headline.
    """

    branding = issue.branding
    source = image_src or asset_image_source
    lines: list[str] = [
        *([masthead_markdown(branding.newsletter_name, logo_src), ""] if logo_src else []),
        f"# {_md_text(issue.body.headline)}",
        "",
        f"**Issue:** {_md_text(branding.newsletter_name)} · Issue {issue.week.number:02d}",
        f"**Week:** {_md_text(window_label(issue))}",
        f"**The assignment:** {_md_text(issue.week.tutorial)}",
        "",
        "## How the week went",
        "",
    ]
    for paragraph in re.split(r"\n\s*\n|\n", issue.body.editorial):
        if paragraph.strip():
            lines.extend([_md_prose(paragraph.strip()), ""])
    lines.extend([f"\u2014 {_md_text(branding.editor_name)}", "", "## Highlights", ""])
    for index in range(1, len(issue.body.highlights) + 1):
        lines.extend(_md_highlight(issue, index, image_src=source))
    lines.extend(
        [
            "\\* " + _md_link(f"{_selection_line(issue)} \u2192", highlights_question_url(issue)),
            "",
            "## All the other builds this week",
            "",
        ]
    )
    others = issue.other_projects()
    if others:
        for link in others:
            built = issue.built_for(link.project_id) or "Nothing posted for this week yet."
            url = link.post_url or link.site_url
            name = _md_link(link.label, url) if url else _md_text(link.label)
            lines.append(f"**{name}:** {_md_text(built)}")
    else:
        lines.append("Everyone who posted made the highlights this week.")
    attribution = _md_text(f"{issue.quote.author}, {issue.quote.source}")
    if issue.quote.url:
        attribution = _md_link(f"{issue.quote.author}, {issue.quote.source}", issue.quote.url)
    lines.extend(
        [
            "",
            "## Last word",
            "",
            f"> \u201c{_md_text(issue.quote.text)}\u201d",
            ">",
            f"> \u2014 {attribution}",
            "",
            "---",
            "",
            f"This newsletter was created by {_md_text(branding.editor_name)}.",
            "",
            f"{_md_text(_course_line(issue))} · Class website: "
            + _md_link(_site_label(branding.course_site_url), branding.course_site_url),
        ]
    )
    if index_uri:
        lines.extend(["", _md_link(f"All issues of {branding.newsletter_name} \u2192", index_uri)])
    return "\n".join(lines).rstrip() + "\n"
