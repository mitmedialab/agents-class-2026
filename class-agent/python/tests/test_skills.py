from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from agent_core import PrincipalContext
from course_server.agent import (
    ReadSkillReferenceTool,
    ReadSkillTool,
    SkillCatalog,
    ToolExecutionContext,
    ToolValidationError,
)

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"


def public_principal() -> PrincipalContext:
    session_id = uuid4()
    return PrincipalContext(
        authenticated=False,
        anonymous_session_id=session_id,
        roles=["public"],
        session_id=session_id,
    )


def authenticated_principal(
    role: Literal["student", "ta", "instructor", "admin"],
) -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=f"test-{role}",
        display_name=f"Test {role.title()}",
        roles=["public", role],
        session_id=uuid4(),
    )


def execution_context(principal: PrincipalContext) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal=principal,
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset(),
    )


def test_skill_catalog_scans_metadata_and_filters_before_disclosure() -> None:
    skills = SkillCatalog.from_registry(SKILLS_ROOT)

    public_ids = {skill.id for skill in skills.authorized_metadata(public_principal())}
    student_ids = {
        skill.id for skill in skills.authorized_metadata(authenticated_principal("student"))
    }
    instructor_ids = {
        skill.id for skill in skills.authorized_metadata(authenticated_principal("instructor"))
    }
    ta_ids = {skill.id for skill in skills.authorized_metadata(authenticated_principal("ta"))}
    admin_ids = {skill.id for skill in skills.authorized_metadata(authenticated_principal("admin"))}

    assert "course-help" in public_ids
    assert "student-course-resources" not in public_ids
    assert "instructor-application-review" not in public_ids
    assert student_ids == public_ids | {"student-course-resources"}
    assert instructor_ids == public_ids | {
        "student-course-resources",
        "instructor-application-review",
    }
    assert ta_ids == admin_ids == public_ids

    course_help = next(
        skill
        for skill in skills.authorized_metadata(public_principal())
        if skill.id == "course-help"
    )
    assert "Use official course resources as the source of truth" not in course_help.description


def test_authenticated_skill_audience_requires_login_for_every_role(tmp_path: Path) -> None:
    skill_directory = tmp_path / "account-help"
    skill_directory.mkdir()
    (skill_directory / "SKILL.md").write_text(
        "---\n"
        "name: account-help\n"
        "description: Help a logged-in user with account-scoped course work.\n"
        "---\n\n"
        "Use only capabilities authorized for the current account.\n",
        encoding="utf-8",
    )
    (tmp_path / "registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "skills": [
                    {
                        "id": "account-help",
                        "directory": "account-help",
                        "audience": "authenticated",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    skills = SkillCatalog.from_registry(tmp_path)

    assert skills.authorized_metadata(public_principal()) == ()
    for role in ("student", "ta", "instructor", "admin"):
        assert [
            skill.id for skill in skills.authorized_metadata(authenticated_principal(role))
        ] == ["account-help"]


def test_skill_body_is_read_when_invoked_instead_of_cached_at_startup(tmp_path: Path) -> None:
    skill_directory = tmp_path / "dynamic-help"
    skill_directory.mkdir()
    skill_path = skill_directory / "SKILL.md"
    metadata = (
        "---\nname: dynamic-help\ndescription: Demonstrate metadata-first skill loading.\n---\n\n"
    )
    skill_path.write_text(metadata + "Initial instructions.\n", encoding="utf-8")
    (tmp_path / "registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "skills": [
                    {
                        "id": "dynamic-help",
                        "directory": "dynamic-help",
                        "audience": "public",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    skills = SkillCatalog.from_registry(tmp_path)
    skill_path.write_text(metadata + "Instructions loaded on demand.\n", encoding="utf-8")

    result = asyncio.run(
        ReadSkillTool(skills).execute(
            {"skill_id": "dynamic-help"},
            execution_context(public_principal()),
        )
    )

    assert "Instructions loaded on demand" in str(result.content)
    assert "Initial instructions" not in str(result.content)


def test_skill_tools_load_full_content_and_references_only_on_demand() -> None:
    async def scenario() -> None:
        skills = SkillCatalog.from_registry(SKILLS_ROOT)
        principal = public_principal()
        context = execution_context(principal)

        with pytest.raises(PermissionError, match="must be loaded"):
            await ReadSkillReferenceTool(skills).execute(
                {
                    "skill_id": "workspace-presentation",
                    "reference_path": "references/visual-composition.md",
                },
                context,
            )

        skill_result = await ReadSkillTool(skills).execute(
            {"skill_id": "workspace-presentation"},
            context,
        )
        assert skill_result.storage_policy == "server_summary"
        assert "preferred presentation surface" in str(skill_result.content)
        assert "references/visual-composition.md" in str(skill_result.content)
        assert "verified quantitative comparisons" not in str(skill_result.content)

        reference_result = await ReadSkillReferenceTool(skills).execute(
            {
                "skill_id": "workspace-presentation",
                "reference_path": "references/visual-composition.md",
            },
            context,
        )
        assert reference_result.storage_policy == "server_summary"
        assert "verified quantitative comparisons" in str(reference_result.content)

    asyncio.run(scenario())


def test_skill_reads_reauthorize_principal_and_confine_reference_paths() -> None:
    async def scenario() -> None:
        skills = SkillCatalog.from_registry(SKILLS_ROOT)

        with pytest.raises(PermissionError):
            await ReadSkillTool(skills).execute(
                {"skill_id": "instructor-application-review"},
                execution_context(public_principal()),
            )

        instructor_result = await ReadSkillTool(skills).execute(
            {"skill_id": "instructor-application-review"},
            execution_context(authenticated_principal("instructor")),
        )
        assert "private data" in str(instructor_result.content)

        public_context = execution_context(public_principal())
        await ReadSkillTool(skills).execute(
            {"skill_id": "workspace-presentation"},
            public_context,
        )

        with pytest.raises(ToolValidationError, match="normalized relative path"):
            await ReadSkillReferenceTool(skills).execute(
                {
                    "skill_id": "workspace-presentation",
                    "reference_path": "../course-application/SKILL.md",
                },
                public_context,
            )

        with pytest.raises(PermissionError, match="not registered"):
            await ReadSkillReferenceTool(skills).execute(
                {
                    "skill_id": "workspace-presentation",
                    "reference_path": "references/missing.md",
                },
                public_context,
            )

    asyncio.run(scenario())
