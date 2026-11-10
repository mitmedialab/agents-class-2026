"""Choose a representative asset from the author's weekly page."""

import re
from html import unescape
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

EXCLUDED = re.compile(
    r"\b(logo|avatar|portrait|headshot|favicon|lecture|reference[s]?|citation|"
    r"paper|bibliography|related work|prior work|inspiration|slides?|architecture|"
    r"diagram|flowchart|langfuse|trace|metrics?|benchmark|chart|plot|heatmap|"
    r"sign[ -]?in|log[ -]?in|oauth|authorization|token|documentation|"
    r"outcome matrix|evidence scores|valence|arousal)\b",
    re.I,
)
DEMO = re.compile(
    r"\b(demo|demos|demonstration|prototype|prototyping|results?|walkthrough|implementation|showcase|output)\b",
    re.I,
)
ARTIFACT = re.compile(
    r"\b(screenshot|viewport|interface|render|simulation|blender|app screens|"
    r"installation|device|working model|room|interaction|in action|physical|hardware|"
    r"assembly|setup|screens?|photo|photograph|preview|ui)\b",
    re.I,
)


def clean_title(value: str) -> str:
    text = " ".join(value.split())
    if (
        not text
        or len(text) > 250
        or re.search(r"[{}\[\]<>|=;]|https?://|\bfunction\s*\(", text)
        or re.fullmatch(r"(?:week|wk)\s*0?\d+", text, re.I)
    ):
        return ""
    return text


def project_description(content: str, title: str) -> str:
    """Pick a short introductory sentence from the indexed author's writing."""
    heading = re.search(r"(?m)^.+\n={3,}\s*$", content)
    body = content[heading.end() :] if heading else content
    for block in re.split(r"\n\s*\n", body):
        text = " ".join(unescape(block).replace("**", "").split())
        if re.search(
            r"https?://|[\[\]{}<>|`]|^[-*#]|\b(?:presented in class|skip to content)\b", text, re.I
        ):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if (
                35 <= len(sentence) <= 280
                and len(sentence.split()) >= 7
                and sentence.endswith((".", "?", "!"))
                and sentence != title
                and not re.match(
                    r"(?:final project proposal by|team:|slides?:|due\b|"
                    r"on this page|I used (?:Claude|ChatGPT))",
                    sentence,
                    re.I,
                )
            ):
                return sentence
    # Some imported portfolio records contain only the author's brief excerpt.
    short = " ".join(unescape(content).replace("*", "").split())
    if (
        "\n" not in content.strip()
        and len(short.split()) >= 4
        and len(short) <= 300
        and short.casefold() != title.casefold()
        and not re.search(r"https?://|[\[\]{}<>|`]", short)
    ):
        return short if len(short) < 100 or short.endswith((".", "?", "!")) else short + "…"
    return ""


def preview_metadata(soup: BeautifulSoup, url: str) -> dict[str, str]:
    headings = soup.select("main h1, article h1") or soup.select("h1")
    titles = [h.get_text(" ", strip=True) for h in headings]
    if soup.title:
        titles.append(soup.title.get_text(" ", strip=True))
    title = next((name for text in titles if (name := clean_title(text))), "")
    best_score, best_url = 0, ""
    for el in soup.select("video[poster], img"):
        if el.find_parent(["nav", "footer", "aside"]):
            continue
        poster = el.name == "video"
        src = el.get("poster") if poster else el.get("data-src") or el.get("src")
        if not isinstance(src, str) or not src:
            continue
        link = urljoin(url, src)
        parsed = urlsplit(link)
        if parsed.scheme != "https" or parsed.netloc != urlsplit(url).netloc:
            continue
        filename = unquote(parsed.path.rsplit("/", 1)[-1])
        fig = el.find_parent("figure")
        caption = fig.find("figcaption") if fig else None
        alt = str(el.get("alt", ""))
        label = " ".join([filename, alt, caption.get_text(" ", strip=True) if caption else ""])
        heading = el.find_previous(["h1", "h2", "h3", "h4"])
        section = heading.get_text(" ", strip=True) if heading else ""
        label = re.sub(r"[-_.]", " ", label)
        # A student's own proposal deck may be the only visual on the weekly page.
        # Require its title on the first slide, never a generic lecture thumbnail.
        title_words = re.findall(r"\w+", title.casefold())
        alt_words = " ".join(re.findall(r"\w+", alt.casefold()))
        title_slide = (
            len(title_words) >= 2
            and " ".join(title_words) in alt_words
            and bool(re.search(r"\bslide\s*0?1\b", label, re.I))
        )
        if title_slide:
            section = re.sub(r"\bslides?\b", "", section, flags=re.I)
            label = re.sub(r"\bslides?\b", "", label, flags=re.I)
        if EXCLUDED.search(label) or EXCLUDED.search(section):
            continue
        if re.search(r"\bresults?\b", section, re.I) and not poster and not ARTIFACT.search(label):
            continue
        score = 100 if poster else int(title_slide)
        score += 25 * bool(DEMO.search(section)) + 18 * bool(DEMO.search(label))
        score += 12 * bool(ARTIFACT.search(label)) + 6 * bool(ARTIFACT.search(section))
        # Images labelled as charts or architecture cannot stand in for the build UI.
        if (
            not poster
            and not title_slide
            and not (
                DEMO.search(section)
                or DEMO.search(label)
                or ARTIFACT.search(label)
                or ARTIFACT.search(section)
            )
        ):
            continue
        if score > best_score:
            best_score, best_url = score, link
    return {"page_title": title, "cover_url": best_url}


def evidence_passages(content: str) -> list[str]:
    """Only readable source sentences can become the automatic borrowing excerpt."""
    return [
        line.strip()
        for line in re.split(r"\n|(?<=[.!?])\s+", content)
        if 40 <= len(line.strip()) <= 320
        and len(line.split()) >= 8
        and line.strip().endswith((".", "!", "?"))
        and not re.search(r"https?://|[|`{}]|!\[|\]\(", line)
        and not re.search(
            r"\b(?:I used (?:Claude|ChatGPT|Codex)|AI (?:assistance|disclosure)|"
            r"diagram made in|presented in class|due (?:Monday|Tuesday))\b",
            line,
            re.I,
        )
    ]


def portfolio_covers(soup: BeautifulSoup, url: str) -> dict[str, str]:
    """Respect the author's cover on a homepage link to a specific weekly build."""
    covers: dict[str, str] = {}
    priorities: dict[str, int] = {}
    for link in soup.select("a[href]"):
        target = urljoin(url, str(link.get("href", ""))).split("#", 1)[0]
        if not re.search(r"(?:week|wk)[-_ /]*0?\d+", urlsplit(target).path, re.I):
            continue
        if link.find_parent(["nav", "footer", "aside"]):
            continue
        for image in link.select("video[poster], img[src], img[data-src]"):
            raw = image.get("poster") or image.get("data-src") or image.get("src")
            if not isinstance(raw, str):
                continue
            asset = urljoin(url, raw)
            name = unquote(urlsplit(asset).path).replace("-", " ").replace("_", " ")
            if re.search(r"\b(?:disc|logo|avatar|favicon|headshot)\b", name, re.I):
                continue
            if urlsplit(asset).scheme != "https" or urlsplit(asset).netloc != urlsplit(url).netloc:
                continue
            priority = 2 if image.name == "video" else 1
            if priority > priorities.get(target, 0):
                covers[target] = asset
                priorities[target] = priority
    return covers
