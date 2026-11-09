"""Source inspection and student-owned personalization, independent of HTTP/UI."""

import asyncio
import hashlib
import logging
import re
import time
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from urllib.parse import unquote, urldefrag, urljoin, urlsplit
from uuid import UUID

from agent_core import PrincipalContext
from course_server.agent.capabilities import ToolValidationError, WebVisitRunner
from course_server.student_projects import StudentProjectCatalog

from .models import (
    Build,
    Catalog,
    Feedback,
    LearningProfile,
    ProfileUpdate,
    Recommendation,
    SavedRecommendation,
    StudentMemory,
    now,
)
from .preview import clean_title, evidence_passages, project_description
from .retrieval import query_terms
from .store import PeerStore

# These are extraction/coverage rules, never chat-intent routing or semantic rankings.
_WEEK = re.compile(r"(?:week|wk)[-_ /]*(0?[1-9]|1[0-4])(?:[^0-9]|$)", re.I)
_LINK = re.compile(r"\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")
MAX_SOURCE_CHARS = 24_000
MAX_PAGES_PER_PROJECT = 8


class PeerAtlas(TypedDict):
    ownAuthor: str
    authors: list[dict[str, object]]
    builds: list[dict[str, object]]
    pairs: list[dict[str, str]]


def student_id(principal: PrincipalContext) -> UUID:
    if not principal.authenticated or "student" not in principal.roles or principal.user_id is None:
        raise ToolValidationError("Sign in as a student to use personal peer discovery.")
    return principal.user_id


def within_site(url: str, root: str) -> bool:
    u, r = urlsplit(url), urlsplit(root)
    prefix = r.path.rstrip("/")
    return (
        u.scheme == "https"
        and not u.username
        and not u.password
        and u.netloc == r.netloc
        and (u.path == prefix or u.path.startswith(prefix + "/"))
        and not u.query
        and not any(part in {".", ".."} for part in unquote(u.path).split("/"))
        and "\\" not in unquote(u.path)
    )


def week_of(url: str) -> int | None:
    match = _WEEK.search(urlsplit(url).path)
    return int(match[1]) if match else None


def source_text(raw: object) -> tuple[str, str | None]:
    if isinstance(raw, str):
        return raw, None
    if isinstance(raw, Mapping) and isinstance(raw.get("text"), str):
        return raw["text"], str(raw.get("url")) if raw.get("url") else None
    raise ValueError("The public page did not contain readable text.")


class PeerDiscovery:
    def __init__(
        self,
        store: PeerStore,
        projects: StudentProjectCatalog,
        visit: WebVisitRunner,
        aliases: Mapping[str, str] | None = None,
        repository_prefix: str = "agents2026-",
    ):
        self.store, self.projects, self.visit = store, projects, visit
        self.aliases = dict(aliases or {})
        self.repository_prefix = repository_prefix
        self._prepare_lock = asyncio.Lock()
        self._next_directory_check = 0.0

    def own_project(self, principal: PrincipalContext) -> str:
        return self.aliases.get(
            (principal.username or "").casefold(),
            self.repository_prefix + (principal.username or ""),
        )

    async def prepare_weekly(self, principal: PrincipalContext) -> dict[str, object]:
        """Reuse the public catalog across students; rank separately for each request."""
        student_id(principal)
        async with self._prepare_lock:
            if time.monotonic() >= self._next_directory_check:
                try:
                    roster = await asyncio.to_thread(self.projects.list_projects)
                    coverage = self.store.catalog().coverage
                    cutoff = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
                    stale = [
                        p.id
                        for p in roster
                        if p.site_url and coverage.get(p.id, {}).get("checked_at", "") < cutoff
                    ]
                    for start in range(0, len(stale), 8):
                        await self.refresh(principal, stale[start : start + 8], [])
                    self._next_directory_check = time.monotonic() + 300
                except Exception as error:
                    logging.getLogger(__name__).warning("Weekly peer source refresh unavailable")
                    self._next_directory_check = time.monotonic() + 30
                    if not self.store.catalog().builds:
                        raise ToolValidationError(
                            "Course websites could not be read. Try again shortly."
                        ) from error
        return self.context(principal)

    def context(self, principal: PrincipalContext) -> dict[str, object]:
        memory = self.store.student(student_id(principal))
        catalog = self.store.catalog()
        builds = {b.id: b for b in catalog.builds}
        return {
            "atlas": self.atlas(principal, memory, catalog),
            "memory": memory.model_dump(mode="json"),
            "recommendations": [
                {
                    **r.model_dump(mode="json"),
                    "build": builds[r.build_id].model_dump(mode="json", exclude={"content"}),
                }
                for r in reversed(memory.recommendations[-12:])
                if r.build_id in builds
            ],
            "coverage": catalog.coverage,
            "indexed_builds": len(catalog.builds),
            "privacy": "Your learning profile and feedback are private to your student account.",
            "freshness": "Opening weekly pairs checks for new course builds.",
        }

    def atlas(
        self, principal: PrincipalContext, memory: StudentMemory, catalog: Catalog
    ) -> PeerAtlas:
        authors: list[dict[str, object]] = [
            {
                "id": key,
                "name": key.removeprefix(self.repository_prefix),
                "site": site,
                "mark": index,
            }
            for index, (key, site) in enumerate(catalog.sites.items())
        ]
        domains = (
            "Learning",
            "Memory",
            "Attention",
            "Reasoning",
            "Creativity",
            "Reflection",
            "Decision-making",
            "Communication",
            "Social connection",
        )
        works = [b for b in catalog.builds if b.project_id in catalog.sites and b.week]
        builds: list[dict[str, object]] = [
            {
                "id": b.id,
                "author": b.project_id,
                "title": b.title,
                "week": b.week,
                "url": b.source_url,
                "image": b.image_url,
                "excerpt": project_description(b.content, b.title),
                "domain": next(
                    (
                        d
                        for d in domains
                        if re.search(r"\b" + re.escape(d) + r"\b", b.title + " " + b.content, re.I)
                    ),
                    "",
                ),
            }
            for b in works
        ]
        own = {b.week: b for b in works if b.project_id == self.own_project(principal)}
        by_id = {b.id: b for b in works}
        pairs = [
            {"mine": own[b.week].id, "peer": b.id, "borrow": r.borrow}
            for r in memory.recommendations
            if (b := by_id.get(r.build_id)) and b.week in own and b.id not in self.dismissed(memory)
        ]
        excluded = self.dismissed(memory)
        ignored = {
            "that",
            "this",
            "with",
            "from",
            "week",
            "build",
            "agent",
            "agents",
            "course",
            "https",
            "github",
            "project",
            "about",
            "what",
            "have",
            "they",
            "will",
            "their",
            "into",
            "when",
            "which",
            "some",
            "more",
            "using",
        }

        def terms(text: str) -> set[str]:
            return set(re.findall(r"[a-z]{4,}", text.casefold())) - ignored

        focus = terms(
            " ".join(
                [
                    memory.profile.long_term_focus,
                    memory.profile.goal,
                    *memory.profile.challenges,
                    *memory.profile.interests,
                ]
            )
        )
        for week, mine in own.items():
            existing = {p["peer"] for p in pairs if p["mine"] == mine.id}
            candidates = [
                b
                for b in works
                if b.week == week
                and b.project_id != mine.project_id
                and b.id not in excluded | existing
            ]
            vocabulary = {b.id: terms(b.title + " " + b.content) for b in candidates}
            frequency = Counter(word for words in vocabulary.values() for word in words)
            anchor = terms(mine.title + " " + mine.content)

            scores = {
                key: 5 * len(words & focus) + sum(1 / frequency[t] for t in words & anchor)
                for key, words in vocabulary.items()
            }
            for peer in sorted(candidates, key=lambda b: (-scores[b.id], b.id)):
                if len(existing) >= 2:
                    break
                passages = evidence_passages(peer.content)
                if not passages:
                    continue
                excerpt = max(
                    passages,
                    key=lambda line: (
                        5 * len(terms(line) & focus)
                        + sum(1 / frequency[t] for t in terms(line) & anchor & vocabulary[peer.id])
                    ),
                )
                existing.add(peer.id)
                pairs.append(
                    {
                        "mine": mine.id,
                        "peer": peer.id,
                        "borrow": f"From the paired build: “{excerpt}”",
                    }
                )
        return {
            "ownAuthor": self.own_project(principal),
            "authors": authors,
            "builds": builds,
            "pairs": pairs,
        }

    def update_profile(
        self,
        principal: PrincipalContext,
        update: ProfileUpdate,
        origin: str,
    ) -> StudentMemory:
        profile = LearningProfile.model_validate(update.model_dump(exclude={"confirmed"}))
        if any(
            len(value) > 300 or not value.strip()
            for value in [*profile.interests, *profile.challenges]
        ):
            raise ToolValidationError(
                "Keep each interest or challenge between 1 and 300 characters."
            )

        def change(state: StudentMemory) -> None:
            if "long_term_focus" not in update.model_fields_set:
                profile.long_term_focus = state.profile.long_term_focus
            state.profile, state.updated_at, state.profile_origin = profile, now(), origin

        return self.store.update_student(student_id(principal), change)

    def feedback(self, principal: PrincipalContext, feedback: Feedback) -> StudentMemory:
        user = student_id(principal)
        indexed_star = feedback.rating in {"saved", "unsaved"} and any(
            b.id == feedback.build_id for b in self.store.catalog().builds
        )
        auto_pair = any(
            pair["peer"] == feedback.build_id
            for pair in self.atlas(principal, self.store.student(user), self.store.catalog())[
                "pairs"
            ]
        )
        if (
            not indexed_star
            and not auto_pair
            and not any(
                r.build_id == feedback.build_id for r in self.store.student(user).recommendations
            )
        ):
            raise ToolValidationError("Feedback must refer to one of your recommendations.")

        def change(state: StudentMemory) -> None:
            state.feedback.append(feedback)
            state.feedback = state.feedback[-200:]
            state.updated_at = now()

        return self.store.update_student(user, change)

    async def refresh(
        self,
        principal: PrincipalContext,
        project_ids: list[str],
        weeks: list[int],
    ) -> dict[str, object]:
        student_id(principal)
        if not 1 <= len(project_ids) <= 8 or len(set(project_ids)) != len(project_ids):
            raise ToolValidationError("Refresh between one and eight distinct course projects.")
        if any(not 1 <= week <= 14 for week in weeks) or len(weeks) > 14:
            raise ToolValidationError("Choose course weeks from 1 to 14.")
        roster = {p.id: p for p in await asyncio.to_thread(self.projects.list_projects)}
        if any(p not in roster for p in project_ids):
            raise ToolValidationError("Choose project IDs from the authorized course directory.")

        def remember_sites(catalog: Catalog) -> None:
            catalog.sites.update(
                {
                    p.id: p.site_url
                    for p in roster.values()
                    if p.site_url and within_site(p.site_url, p.site_url)
                }
            )

        self.store.update_catalog(remember_sites)
        semaphore = asyncio.Semaphore(4)

        async def inspect(project_id: str) -> dict[str, object]:
            async with semaphore:
                project = roster[project_id]
                root = project.site_url
                stamp = now()
                records: list[Build] = []
                statuses: dict[str, str] = {}
                if not root or not within_site(root, root):
                    return {"project_id": project_id, "error": "No HTTPS course website is listed."}
                try:
                    home = await asyncio.to_thread(self.visit, root)
                    homepage, final = source_text(home)
                    home_covers = (
                        home.get("portfolio_covers", {}) if isinstance(home, Mapping) else {}
                    )
                    if final and not within_site(final, root):
                        raise ValueError("Redirect left the listed course site.")
                except Exception:
                    return {
                        "project_id": project_id,
                        "error": "Website unavailable; coverage unknown.",
                    }
                # Only discovered links, never guessed week URLs. Fragments are intentionally
                # excluded: one root-page anchor is not a separately verified weekly build.
                urls = []
                for match in _LINK.finditer(homepage):
                    url = urldefrag(urljoin(root, match[1]))[0]
                    week = week_of(url)
                    if (
                        within_site(url, root)
                        and not re.search(
                            r"\.(?:png|jpe?g|gif|svg|webp|mp4|webm|pdf)$", urlsplit(url).path, re.I
                        )
                        and week
                        and (not weeks or week in weeks)
                        and url not in urls
                    ):
                        urls.append(url)
                for url in sorted(urls, key=lambda u: week_of(u) or 0, reverse=True)[
                    :MAX_PAGES_PER_PROJECT
                ]:
                    try:
                        page = await asyncio.to_thread(self.visit, url)
                        content, final = source_text(page)
                        cover = home_covers.get(url) if isinstance(home_covers, Mapping) else None
                        if not cover:
                            cover = page.get("cover_url") if isinstance(page, Mapping) else None
                        image_url = (
                            cover if isinstance(cover, str) and within_site(cover, root) else None
                        )
                        if final and not within_site(final, root):
                            raise ValueError("Redirect left the listed course site.")
                        if len(content.strip()) < 100:
                            raise ValueError("Insufficient readable evidence.")
                        title = (
                            clean_title(str(page.get("page_title") or ""))
                            if isinstance(page, Mapping)
                            else ""
                        )
                        if not title:
                            titles = re.findall(r"(?m)^#{1,2}\s+(.+)$", content)
                            title = next(
                                (clean_title(h) for h in titles if clean_title(h)),
                                f"{project_id} · Week {week_of(url)}",
                            )
                        records.append(
                            Build(
                                id="build-" + hashlib.sha256(url.encode()).hexdigest()[:16],
                                project_id=project_id,
                                week=week_of(url),
                                title=title[:250],
                                source_url=url,
                                image_url=image_url,
                                content=content[:MAX_SOURCE_CHARS],
                                source_hash=hashlib.sha256(content.encode()).hexdigest(),
                                observed_at=stamp,
                                truncated=len(content) > MAX_SOURCE_CHARS,
                            )
                        )
                        statuses[url] = "indexed"
                    except Exception:
                        statuses[url] = "unavailable; coverage unknown"
                if not urls:
                    statuses[root] = "No separate weekly links discovered; use site inspection."

                def merge(catalog: Catalog) -> None:
                    by_id = {b.id: b for b in catalog.builds}
                    for record in records:
                        previous = by_id.get(record.id)
                        if previous and previous.reviewed_title:
                            record.reviewed_title = previous.reviewed_title
                            record.title = previous.reviewed_title
                        by_id[record.id] = record
                    catalog.builds = list(by_id.values())
                    catalog.coverage[project_id] = {
                        "checked_at": stamp,
                        **statuses,
                        "limit": f"Read up to {MAX_PAGES_PER_PROJECT} discovered weekly pages.",
                    }

                self.store.update_catalog(merge)
                return {"project_id": project_id, "indexed": len(records), "coverage": statuses}

        return {"results": await asyncio.gather(*(inspect(p) for p in project_ids))}

    @staticmethod
    def dismissed(memory: StudentMemory) -> set[str]:
        latest = {
            f.build_id: f.rating
            for f in memory.feedback
            if f.rating in {"not_relevant", "already_seen", "helpful"}
        }
        return {key for key, rating in latest.items() if rating in {"not_relevant", "already_seen"}}

    def query(
        self,
        principal: PrincipalContext,
        query: str = "",
        week: int | None = None,
    ) -> dict[str, object]:
        user = student_id(principal)
        memory, catalog = self.store.student(user), self.store.catalog()
        dismissed = self.dismissed(memory)
        terms = query_terms(query)
        needs = " ".join(
            [
                memory.profile.long_term_focus,
                memory.profile.goal,
                *memory.profile.challenges,
                *memory.profile.interests,
            ]
        )
        profile_terms = set(re.findall(r"[\w-]{3,}", needs.casefold())) - {
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
        }
        candidates = [
            b
            for b in catalog.builds
            if b.project_id != self.own_project(principal)
            and b.id not in dismissed
            and (week is None or b.week == week)
        ]

        def score(b: Build) -> int:
            content = (b.title + " " + b.content).casefold()
            return 2 * sum(term in content for term in terms) + sum(
                term in content for term in profile_terms
            )

        if query.strip() and not terms:
            candidates = []
        if terms:
            candidates = [
                b
                for b in candidates
                if any(term in (b.title + " " + b.content).casefold() for term in terms)
            ]
        candidates.sort(key=lambda b: (-score(b), b.project_id, b.id))
        return {
            "candidates": [b.model_dump(exclude={"content"}) for b in candidates[:24]],
            "indexed_builds": len(catalog.builds),
            "coverage": catalog.coverage,
            "retrieval": "Lexical shortlist only; read sources and compare before recommending.",
        }

    def read_build(self, principal: PrincipalContext, build_id: str) -> Build:
        student_id(principal)
        build = next((b for b in self.store.catalog().builds if b.id == build_id), None)
        if build is None:
            raise ToolValidationError(
                "Build is not indexed; refresh its verified public source first."
            )
        return build

    def save(
        self,
        principal: PrincipalContext,
        picks: list[Recommendation],
        seen: dict[str, str],
    ) -> StudentMemory:
        user = student_id(principal)
        if not 1 <= len(picks) <= 4 or len({p.build_id for p in picks}) != len(picks):
            raise ToolValidationError("Choose one to four distinct source-supported builds.")
        catalog = {b.id: b for b in self.store.catalog().builds}
        eligible = {b.id for b in catalog.values() if b.project_id != self.own_project(principal)}
        if len(eligible & seen.keys()) < min(2, len(eligible)):
            raise ToolValidationError(
                "Read at least two eligible candidate sources for comparison."
            )
        state = self.store.student(user)
        dismissed = self.dismissed(state)
        for pick in picks:
            build = catalog.get(pick.build_id)
            if build is None or pick.build_id not in eligible or pick.build_id in dismissed:
                raise ToolValidationError(
                    "Unknown, own, or dismissed builds cannot be recommended."
                )
            if seen.get(build.id) != build.source_hash:
                raise ToolValidationError("Read the current source snapshot before recommending.")
            if pick.evidence_quote not in build.content:
                raise ToolValidationError(
                    "The evidence quote must occur verbatim in the read source."
                )

        def change(memory: StudentMemory) -> None:
            memory.recommendations = [
                r for r in memory.recommendations if r.build_id not in {p.build_id for p in picks}
            ]
            memory.recommendations.extend(
                SavedRecommendation(**p.model_dump(), profile=memory.profile.model_copy(deep=True))
                for p in picks
            )
            memory.recommendations = memory.recommendations[-100:]
            memory.updated_at = now()

        return self.store.update_student(user, change)
