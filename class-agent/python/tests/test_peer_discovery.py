"""Source evidence, persistent personalization and authorization regression tests."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from agent_core import PrincipalContext
from course_server.agent.capabilities import ToolExecutionContext, ToolValidationError
from course_server.peer_discovery.models import Build, Feedback, ProfileUpdate, Recommendation
from course_server.peer_discovery.service import PeerDiscovery, within_site
from course_server.peer_discovery.store import PeerStore
from course_server.peer_discovery.tools import PeerTool
from course_server.student_projects import StudentProject
from course_server.workspace.registry import load_component_registry


class Projects:
    def list_projects(self) -> list[StudentProject]:
        return [
            StudentProject("agents2026-ada", "https://example.edu/ada/"),
            StudentProject("agents2026-grace", "https://example.edu/grace/"),
        ]


def student(name: str = "raine") -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=name,
        roles=["public", "student"],
        session_id=uuid4(),
    )


def visit(url: str) -> dict[str, object]:
    if url.endswith("week01/"):
        return {
            "url": url,
            "text": "# Voice prototype\n"
            + "The visitor can pause the voice agent and choose when to continue. " * 4,
        }
    return {
        "url": url,
        "text": "# Projects\n[Week 1](week01/)\n[Unsafe](https://evil.example/week02/)",
    }


@pytest.fixture
def service(tmp_path: Path) -> PeerDiscovery:
    return PeerDiscovery(PeerStore(tmp_path), Projects(), visit)  # type: ignore[arg-type]


def test_profile_persists_and_is_isolated(service: PeerDiscovery) -> None:
    alice, bob = student(), student("bob")
    update = ProfileUpdate(
        goal="Museum voice agent", challenges=["Visitor control"], confirmed=True
    )
    service.update_profile(alice, update, "Student form")
    reloaded = PeerDiscovery(PeerStore(service.store.directory), Projects(), visit)  # type: ignore[arg-type]
    assert reloaded.context(alice)["memory"]["profile"]["goal"] == "Museum voice agent"  # type: ignore[index]
    assert service.store.student(bob.user_id).profile.goal == ""  # type: ignore[arg-type]
    assert service.store.student(alice.user_id).profile_origin == "Student form"  # type: ignore[arg-type]


def test_anonymous_and_staff_cannot_read_private_memory(service: PeerDiscovery) -> None:
    anonymous = PrincipalContext(
        authenticated=False, anonymous_session_id=uuid4(), roles=["public"], session_id=uuid4()
    )
    with pytest.raises(ToolValidationError):
        service.context(anonymous)
    staff = student().model_copy(update={"roles": ["public", "instructor"]})
    with pytest.raises(ToolValidationError):
        service.context(staff)


def test_site_scope_is_exact_not_string_prefix() -> None:
    assert within_site("https://example.edu/ada/week01/", "https://example.edu/ada/")
    for url in [
        "https://example.edu/adam/week01/",
        "https://evil.example/ada/week01/",
        "http://example.edu/ada/",
        "https://x@example.edu/ada/",
    ]:
        assert not within_site(url, "https://example.edu/ada/")


def test_refresh_reads_only_discovered_in_scope_weeks(service: PeerDiscovery) -> None:
    result = asyncio.run(service.refresh(student(), ["agents2026-ada"], [1]))
    assert result["results"][0]["indexed"] == 1  # type: ignore[index]
    build = service.store.catalog().builds[0]
    assert build.week == 1 and build.source_url == "https://example.edu/ada/week01/"
    assert build.source_hash and build.observed_at
    with pytest.raises(ToolValidationError):
        asyncio.run(service.refresh(student(), ["agents2026-outside"], []))


def test_missing_links_are_unknown_not_missing_submissions(service: PeerDiscovery) -> None:
    service.visit = lambda url: "# A single-page project without separate weekly pages."
    asyncio.run(service.refresh(student(), ["agents2026-ada"], []))
    assert not service.store.catalog().builds
    assert "No separate weekly links" in str(service.store.catalog().coverage)


def seed(service: PeerDiscovery, principal: PrincipalContext) -> list[Build]:
    asyncio.run(service.refresh(principal, ["agents2026-ada", "agents2026-grace"], [1]))
    return service.store.catalog().builds


def recommendation(
    build_id: str, quote: str = "The visitor can pause the voice agent"
) -> Recommendation:
    return Recommendation(
        build_id=build_id,
        reason="A useful reference for visitor control.",
        borrow="Offer an explicit pause and resume choice.",
        evidence_quote=quote,
    )


def test_source_comparison_and_quotes_are_enforced(service: PeerDiscovery) -> None:
    user = student()
    builds = seed(service, user)
    seen = {b.id: b.source_hash for b in builds}
    with pytest.raises(ToolValidationError, match="two eligible"):
        service.save(user, [recommendation(builds[0].id)], {builds[0].id: builds[0].source_hash})
    with pytest.raises(ToolValidationError, match="verbatim"):
        service.save(
            user, [recommendation(builds[0].id, "A quote that the source never stated.")], seen
        )
    with pytest.raises(ToolValidationError, match="current source"):
        service.save(user, [recommendation(builds[0].id)], {**seen, builds[0].id: "stale"})
    assert service.save(user, [recommendation(builds[0].id)], seen).recommendations


def test_feedback_changes_later_candidates(service: PeerDiscovery) -> None:
    user = student()
    builds = seed(service, user)
    seen = {b.id: b.source_hash for b in builds}
    service.save(user, [recommendation(builds[0].id)], seen)
    service.feedback(
        user, Feedback(build_id=builds[0].id, rating="not_relevant", note="More interface examples")
    )
    candidates = service.query(user)["candidates"]
    assert builds[0].id not in str(candidates)
    assert builds[1].id in str(candidates)
    with pytest.raises(ToolValidationError):
        service.save(user, [recommendation(builds[0].id)], seen)


def test_profile_correction_preserves_recommendation_provenance(service: PeerDiscovery) -> None:
    user = student()
    builds = seed(service, user)
    service.update_profile(user, ProfileUpdate(goal="Hardware", confirmed=True), "Student form")
    service.save(user, [recommendation(builds[0].id)], {b.id: b.source_hash for b in builds})
    service.update_profile(
        user, ProfileUpdate(goal="Screen-free interaction", confirmed=True), "Correction"
    )
    memory = service.store.student(user.user_id)  # type: ignore[arg-type]
    assert memory.profile.goal == "Screen-free interaction"
    assert memory.recommendations[0].profile.goal == "Hardware"
    service.store.forget(user.user_id)  # type: ignore[arg-type]
    assert service.store.student(user.user_id).profile.goal == ""  # type: ignore[arg-type]
    assert len(service.store.catalog().builds) == 2


def test_tool_opens_registered_native_workspace(service: PeerDiscovery) -> None:
    context = ToolExecutionContext(
        principal=student(), conversation_id=uuid4(), permitted_resource_uris=frozenset()
    )
    tool = PeerTool("get_context", service, load_component_registry())
    result = asyncio.run(tool.execute({}, context))
    assert result.emitted_events and result.storage_policy == "server_summary"
    assert "peer-discovery" in str(result.emitted_events)
    with pytest.raises(ToolValidationError):
        asyncio.run(tool.execute({"user_id": str(uuid4())}, context))


def test_open_weekly_pairs_without_chat_or_saved_recommendations(service: PeerDiscovery) -> None:
    user = student("ada")
    result = asyncio.run(service.prepare_weekly(user))
    atlas = result["atlas"]
    assert isinstance(atlas, dict)
    pairs = atlas["pairs"]
    assert len(pairs) == 1
    assert user.user_id is not None
    assert not service.store.student(user.user_id).recommendations
    assert pairs[0]["borrow"] == pairs[0]["reason"]
    assert "interrupt each voice interaction" in pairs[0]["reason"]
    service.feedback(user, Feedback(build_id=pairs[0]["peer"], rating="not_relevant"))
    updated = asyncio.run(service.prepare_weekly(user))["atlas"]
    assert isinstance(updated, dict)
    assert updated["pairs"] == []


def test_chat_query_emits_only_matching_peer_builds(service: PeerDiscovery) -> None:
    user = student("ada")
    asyncio.run(service.refresh(user, ["agents2026-ada", "agents2026-grace"], [1]))
    ctx = ToolExecutionContext(
        principal=user, conversation_id=uuid4(), permitted_resource_uris=frozenset()
    )
    tool = PeerTool("query_builds", service, load_component_registry())
    for query, count in [
        ("voice", 1),
        ("我想学习语音交互", 1),
        ("I need help", 0),
        ("unrepresented", 0),
    ]:
        reply = asyncio.run(tool.execute({"query": query}, ctx))
        assert isinstance(reply.content, dict)
        candidates = reply.content["candidates"]
        assert isinstance(candidates, list) and len(candidates) == count
        command = reply.emitted_events[0].payload["command"]
        assert isinstance(command, dict)
        panel = command["panel"]
        assert isinstance(panel, dict)
        assert panel["props"] == {
            "view": "recommendations",
            "build_ids": [b["id"] for b in candidates if isinstance(b, dict)],
        }


def test_refresh_prefers_author_homepage_cover(service: PeerDiscovery) -> None:
    root = "https://example.edu/ada/"
    cover = root + "assets/week01/demo-cover.jpg"

    def curated_visit(url: str) -> dict[str, object]:
        result = visit(url)
        if url == root:
            result["portfolio_covers"] = {root + "week01/": cover}
        else:
            result["cover_url"] = root + "assets/frog-idle.png"
        return result

    service.visit = curated_visit
    asyncio.run(service.refresh(student(), ["agents2026-ada"], [1]))
    assert service.store.catalog().builds[0].image_url == cover


def test_weekly_reason_distinguishes_shared_work_from_a_saved_focus(service: PeerDiscovery) -> None:
    user = student("ada")
    builds = seed(service, user)
    catalog = service.store.catalog()
    own, peer = sorted(builds, key=lambda b: b.project_id)
    own = own.model_copy(
        update={
            "title": "Rehearsal",
            "content": "Practise a difficult conversation by choosing what to say next.",
        }
    )
    peer = peer.model_copy(
        update={
            "title": "Garden monitor",
            "content": "The sensor measures moisture and lets a gardener know when to water.",
        }
    )
    catalog = catalog.model_copy(update={"builds": [own, peer]})
    assert user.user_id is not None
    memory = service.store.student(user.user_id)
    assert service.atlas(user, memory, catalog)["pairs"] == []
    memory.profile.interests = ["sensor input"]
    reason = service.atlas(user, memory, catalog)["pairs"][0]["reason"]
    assert "your saved focus on sensor input" in reason
    assert "Both write-ups" not in reason


def test_cross_topic_pair_suggests_a_transfer_from_the_peer_method(service: PeerDiscovery) -> None:
    user = student("ada")
    own, peer = sorted(seed(service, user), key=lambda b: b.project_id)
    own = own.model_copy(
        update={
            "title": "Gallery guide",
            "content": "A voice companion for museum visitors who want to discuss an artwork.",
        }
    )
    peer = peer.model_copy(
        update={
            "title": "Final proposal",
            "content": (
                "A multi-agent network for promoting creativity and reducing "
                "homogeneity of thought."
            ),
        }
    )
    catalog = service.store.catalog().model_copy(update={"builds": [own, peer]})
    assert user.user_id is not None
    reason = service.atlas(user, service.store.student(user.user_id), catalog)["pairs"][0]["reason"]
    assert "several agents" in reason and "two readings of the same artwork" in reason


def test_weekly_pair_uses_saved_recommendation_reason(service: PeerDiscovery) -> None:
    user = student("ada")
    builds = seed(service, user)
    peer = next(b for b in builds if b.project_id == "agents2026-grace")
    rec = recommendation(peer.id)
    service.save(user, [rec], {b.id: b.source_hash for b in builds})
    assert user.user_id is not None
    pair = service.atlas(user, service.store.student(user.user_id), service.store.catalog())[
        "pairs"
    ][0]
    assert pair["reason"] == rec.reason
    assert pair["borrow"] == rec.borrow
