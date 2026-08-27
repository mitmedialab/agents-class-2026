from __future__ import annotations

import asyncio
import json
import stat
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from agent_core import PrincipalContext
from course_server.agent import (
    COURSE_APPLICATION_URI,
    COURSE_FAQ_URI,
    COURSE_INSTRUCTORS_URI,
    COURSE_SCHEDULE_URI,
    COURSE_SYLLABUS_URI,
    CourseGetApplicationTool,
    CourseReadPublicFileTool,
    CourseSearchFaqTool,
    CourseSearchTool,
    CourseShowPublicFilesTool,
    CourseSubmitApplicationTool,
    FileApplicantStore,
    FileResourceProvider,
    PublicImageSearchTool,
    PublicVisitWebpageTool,
    PublicWebSearchTool,
    ReadTemporaryUploadTool,
    ToolExecutionContext,
    ToolValidationError,
    load_resource_definitions,
)
from course_server.uploads import FileTemporaryUploadStore


def public_principal() -> PrincipalContext:
    session_id = uuid4()
    return PrincipalContext(
        authenticated=False,
        anonymous_session_id=session_id,
        roles=["public"],
        session_id=session_id,
    )


def execution_context(*resource_uris: str) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal=public_principal(),
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset(resource_uris),
    )


def test_temporary_upload_tool_reads_the_owned_artifact_without_substitution(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        principal = public_principal()
        uploads = FileTemporaryUploadStore(tmp_path / "uploads")
        receipt = await uploads.store(
            filename="methods.md",
            media_type="text/markdown",
            content=b"# Methods\n\nThirty-four participants completed the study.",
            principal=principal,
        )
        resource_uri = f"upload://{receipt.id}"
        result = await ReadTemporaryUploadTool(uploads).execute(
            {"upload_id": str(receipt.id)},
            ToolExecutionContext(
                principal=principal,
                conversation_id=uuid4(),
                permitted_resource_uris=frozenset({resource_uri}),
            ),
        )

        assert "Thirty-four participants" in str(result.content)
        assert result.resource_uris == [resource_uri]
        assert result.storage_policy == "server_summary"

    asyncio.run(scenario())


def test_temporary_upload_tool_extracts_text_from_the_uploaded_pdf(tmp_path: Path) -> None:
    pdf = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Thirty-four participants completed the study.) Tj ET")
    page[NameObject("/Contents")] = stream
    writer.write(pdf)

    async def scenario() -> None:
        principal = public_principal()
        uploads = FileTemporaryUploadStore(tmp_path / "uploads")
        receipt = await uploads.store(
            filename="study.pdf",
            media_type="application/pdf",
            content=pdf.getvalue(),
            principal=principal,
        )
        resource_uri = f"upload://{receipt.id}"
        result = await ReadTemporaryUploadTool(uploads).execute(
            {"upload_id": str(receipt.id)},
            ToolExecutionContext(
                principal=principal,
                conversation_id=uuid4(),
                permitted_resource_uris=frozenset({resource_uri}),
            ),
        )

        assert "--- Page 1 ---" in str(result.content)
        assert "Thirty-four participants completed the study" in str(result.content)
        assert result.resource_uris == [resource_uri]

    asyncio.run(scenario())


def test_public_resource_registry_includes_provisional_schedule() -> None:
    resources = FileResourceProvider.from_registry()

    summaries = resources.list_public()

    assert [summary.uri for summary in summaries] == [
        "course://syllabus",
        "course://schedule",
        "course://repositories",
        "course://faq",
        "course://instructors",
        "course://application",
    ]
    instructors = next(summary for summary in summaries if summary.uri == COURSE_INSTRUCTORS_URI)
    assert instructors.title == "Course Staff"
    schedule = next(summary for summary in summaries if summary.uri == COURSE_SCHEDULE_URI)
    assert schedule.status == "provisional"
    assert schedule.description == "Provisional weekly topics, tutorials, speakers, and readings."

    schedule_contents = asyncio.run(resources.read(COURSE_SCHEDULE_URI))
    schedule_data = json.loads(schedule_contents.text)
    assert schedule_contents.media_type == "application/json"
    assert schedule_data["status"] == "provisional"
    assert len(schedule_data["weeks"]) == 13

    instructor_contents = asyncio.run(resources.read(COURSE_INSTRUCTORS_URI))
    assert "Pattie Maes" in instructor_contents.text
    assert "Yasith Samaradivakara" in instructor_contents.text
    assert "portraits/pattie_maes.jpg" in instructor_contents.text
    assert "portraits/yasith_samaradivakara.jpg" in instructor_contents.text
    assert "Recent profile photo uploaded in chat" in instructor_contents.text

    instructors_definition = next(
        resource
        for resource in load_resource_definitions()
        if resource.uri == COURSE_INSTRUCTORS_URI
    )
    assert sorted(instructors_definition.assets) == [
        "chitralekha_gupta_portrait",
        "pattie_maes_portrait",
        "rachel_poonsiriwong_portrait",
        "valdemar_danry_portrait",
        "wazeer_zulfikar_portrait",
        "yasith_samaradivakara_portrait",
    ]


def test_public_resource_contents_do_not_expose_internal_resource_identifiers() -> None:
    async def scenario() -> None:
        resources = FileResourceProvider.from_registry()
        for summary in resources.list_public():
            contents = await resources.read(summary.uri)
            assert "course://" not in contents.text

    asyncio.run(scenario())


def test_resource_registry_rejects_paths_outside_shared_root(tmp_path: Path) -> None:
    registry_directory = tmp_path / "shared/registry"
    registry_directory.mkdir(parents=True)
    registry = {
        "schema_version": 1,
        "resources": [
            {
                "uri": "course://unsafe",
                "title": "Unsafe",
                "media_type": "text/plain",
                "path": "../outside.txt",
            }
        ],
    }
    registry_path = registry_directory / "resources.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(ValueError, match="leaves shared root"):
        FileResourceProvider.from_registry(registry_path)


def test_course_search_respects_authorized_resource_filter() -> None:
    async def scenario() -> None:
        resources = FileResourceProvider.from_registry()
        tool = CourseSearchTool(resources)
        syllabus_only = execution_context(COURSE_SYLLABUS_URI)

        result = await tool.execute(
            {"query": "cognitive augmentation", "limit": 4},
            syllabus_only,
        )

        assert isinstance(result.content, list)
        assert result.content
        assert {item["uri"] for item in result.content if isinstance(item, dict)} == {
            COURSE_SYLLABUS_URI
        }
        assert result.resource_uris == [COURSE_SYLLABUS_URI]

        no_access = await tool.execute(
            {"query": "cognitive augmentation"},
            execution_context(),
        )
        assert no_access.content == []
        assert no_access.resource_uris == []

    asyncio.run(scenario())


def test_schedule_search_excerpt_is_centered_on_later_week_match() -> None:
    async def scenario() -> None:
        resources = FileResourceProvider.from_registry()
        result = await CourseSearchTool(resources).execute(
            {"query": "physiology-aware"},
            execution_context(COURSE_SCHEDULE_URI),
        )

        assert isinstance(result.content, list)
        assert result.content
        first = result.content[0]
        assert isinstance(first, dict)
        assert "physiology-aware" in str(first["excerpt"])
        assert first["status"] == "provisional"

    asyncio.run(scenario())


def test_public_file_listing_has_metadata_but_no_server_paths() -> None:
    async def scenario() -> None:
        resources = FileResourceProvider.from_registry()
        result = await CourseShowPublicFilesTool(resources).execute(
            {},
            execution_context(COURSE_SYLLABUS_URI, COURSE_SCHEDULE_URI),
        )

        assert isinstance(result.content, list)
        assert [item["uri"] for item in result.content if isinstance(item, dict)] == [
            COURSE_SYLLABUS_URI,
            COURSE_SCHEDULE_URI,
        ]
        assert all("path" not in item for item in result.content if isinstance(item, dict))

    asyncio.run(scenario())


def test_read_public_file_rejects_resource_not_authorized_for_run() -> None:
    async def scenario() -> None:
        resources = FileResourceProvider.from_registry()
        tool = CourseReadPublicFileTool(resources)

        with pytest.raises(PermissionError, match="not authorized"):
            await tool.execute(
                {"resource_uri": COURSE_FAQ_URI},
                execution_context(COURSE_SYLLABUS_URI),
            )

    asyncio.run(scenario())


def test_faq_search_is_scoped_to_public_faq() -> None:
    async def scenario() -> None:
        resources = FileResourceProvider.from_registry()
        result = await CourseSearchFaqTool(resources).execute(
            {"query": "applications admissions"},
            execution_context(COURSE_FAQ_URI, COURSE_SYLLABUS_URI),
        )

        assert result.resource_uris == [COURSE_FAQ_URI]
        assert isinstance(result.content, list)
        assert all(
            item["uri"] == COURSE_FAQ_URI for item in result.content if isinstance(item, dict)
        )

    asyncio.run(scenario())


def test_application_information_tool_reads_official_guide_directly() -> None:
    async def scenario() -> None:
        result = await CourseGetApplicationTool(FileResourceProvider.from_registry()).execute(
            {},
            execution_context(COURSE_APPLICATION_URI),
        )

        assert isinstance(result.content, str)
        assert "Capacity | 25 in-person students" in result.content
        assert "Email" in result.content
        assert "Recent profile photo" in result.content
        assert "ask only for the applicant's full name" in result.content
        assert "every required field has a supported candidate value" in result.content
        assert "later field-by-field interview" in result.content
        assert result.resource_uris == [COURSE_APPLICATION_URI]

    asyncio.run(scenario())


def test_public_web_tools_wrap_search_and_page_reading_without_persisting_results() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        def search(query: str) -> str:
            calls.append(query)
            return "[Example profile](https://8.8.8.8/profile)"

        def visit(url: str) -> str:
            calls.append(url)
            return "# Public profile"

        search_result = await PublicWebSearchTool(search).execute(
            {"query": '"Ada Lovelace"'},
            execution_context(),
        )
        page_result = await PublicVisitWebpageTool(visit).execute(
            {"url": "https://8.8.8.8/profile"},
            execution_context(),
        )

        assert calls == ['"Ada Lovelace"', "https://8.8.8.8/profile"]
        assert search_result.content == "[Example profile](https://8.8.8.8/profile)"
        assert page_result.content == "# Public profile"
        assert search_result.storage_policy == "server_summary"
        assert page_result.storage_policy == "server_summary"

        with pytest.raises(ToolValidationError, match="public internet addresses"):
            await PublicVisitWebpageTool(visit).execute(
                {"url": "http://127.0.0.1/private"},
                execution_context(),
            )

    asyncio.run(scenario())


def test_public_image_search_normalizes_https_candidates_for_workspace_images() -> None:
    async def scenario() -> None:
        calls: list[tuple[str, int]] = []

        def search(query: str, limit: int) -> list[dict[str, object]]:
            calls.append((query, limit))
            return [
                {
                    "title": "  Fluid Interfaces  ",
                    "image": "https://images.example.org/fluid.jpg",
                    "thumbnail": "https://images.example.org/fluid-thumb.jpg",
                    "url": "https://www.example.org/fluid",
                    "source": "Example",
                    "width": "1600",
                    "height": 900,
                },
                {
                    "title": "Duplicate",
                    "image": "https://images.example.org/fluid.jpg",
                },
                {
                    "title": "HTTPS thumbnail fallback",
                    "image": "http://images.example.org/insecure.jpg",
                    "thumbnail": "https://images.example.org/fallback-thumb.jpg",
                },
                {
                    "title": "Private address",
                    "image": "https://127.0.0.1/private.jpg",
                },
                {
                    "title": "Second result",
                    "image": "https://cdn.example.org/second.jpg",
                    "thumbnail": "http://cdn.example.org/second-thumb.jpg",
                    "url": "http://www.example.org/second",
                },
            ]

        result = await PublicImageSearchTool(search).execute(
            {"query": "MIT Media Lab Fluid Interfaces", "limit": 4},
            execution_context(),
        )

        assert calls == [("MIT Media Lab Fluid Interfaces", 4)]
        assert result.content == {
            "query": "MIT Media Lab Fluid Interfaces",
            "results": [
                {
                    "title": "Fluid Interfaces",
                    "image_url": "https://images.example.org/fluid.jpg",
                    "thumbnail_url": "https://images.example.org/fluid-thumb.jpg",
                    "source_page_url": "https://www.example.org/fluid",
                    "source": "Example",
                    "width": 1600,
                    "height": 900,
                },
                {
                    "title": "HTTPS thumbnail fallback",
                    "image_url": "https://images.example.org/fallback-thumb.jpg",
                    "thumbnail_url": "https://images.example.org/fallback-thumb.jpg",
                },
                {
                    "title": "Second result",
                    "image_url": "https://cdn.example.org/second.jpg",
                },
            ],
        }
        assert result.summary == "Found 3 public image candidates."
        assert result.storage_policy == "server_summary"

        with pytest.raises(ToolValidationError, match="no usable HTTPS images"):
            await PublicImageSearchTool(
                lambda _query, _limit: [{"image": "http://example.org/image.jpg"}]
            ).execute({"query": "example"}, execution_context())

    asyncio.run(scenario())


def test_application_tool_stores_private_json_with_server_generated_name(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        principal = public_principal()
        context = ToolExecutionContext(
            principal=principal,
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset({COURSE_APPLICATION_URI}),
        )
        uploads = FileTemporaryUploadStore(tmp_path / "uploads")
        photo = await uploads.store(
            filename="portrait.png",
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\nphoto-data",
            principal=principal,
        )
        tool = CourseSubmitApplicationTool(
            FileApplicantStore(tmp_path / "applicants"),
            uploads,
        )
        application = {
            "name": "Ada Applicant",
            "email": "ada@example.edu",
            "department_research_group_year_of_study_mit": (
                "Media Lab, Fluid Interfaces, second year"
            ),
            "personal_webpage": "https://example.edu/ada",
            "interests": "Learning agents and human agency",
            "why_take_this_class": (
                "I want to understand how agent interaction can augment learning without "
                "weakening student agency."
            ),
            "knowledgeable_about": "Human-computer interaction and learning sciences",
            "skill_set": "Python, TypeScript, interface design, qualitative research",
            "registration_status": "MAS student for credit",
            "listener_willing_to_do_weekly_builds": "Not applicable; taking for credit",
            "questions_or_comments_for_instructors": "No questions",
            "photo_upload_id": str(photo.id),
        }

        with pytest.raises(ToolValidationError, match="registration_status"):
            await tool.execute(
                {**application, "registration_status": "Taking for credit"},
                context,
            )

        result = await tool.execute(application, context)

        assert result.storage_policy == "server_summary"
        assert application["why_take_this_class"] not in (result.summary or "")
        stored_directories = list((tmp_path / "applicants").glob("*_*"))
        assert len(stored_directories) == 1
        application_file = stored_directories[0] / "application.json"
        stored = json.loads(application_file.read_text(encoding="utf-8"))
        assert stored["application"]["name"] == "Ada Applicant"
        assert stored["application"]["photo_upload_id"] == str(photo.id)
        assert stored["principal"]["anonymous_session_id"] is not None
        photo_file = stored_directories[0] / "photo.png"
        assert photo_file.read_bytes() == b"\x89PNG\r\n\x1a\nphoto-data"
        assert stat.S_IMODE(application_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(photo_file.stat().st_mode) == 0o600

    asyncio.run(scenario())


def test_application_tool_reports_every_incomplete_field(tmp_path: Path) -> None:
    async def scenario() -> None:
        tool = CourseSubmitApplicationTool(
            FileApplicantStore(tmp_path / "applicants"),
            FileTemporaryUploadStore(tmp_path / "uploads"),
        )

        with pytest.raises(ToolValidationError) as raised:
            await tool.execute(
                {"name": "Ada", "email": "not-an-email"},
                execution_context(COURSE_APPLICATION_URI),
            )

        message = str(raised.value)
        assert "email" in message
        assert "photo_upload_id" in message
        assert "registration_status" in message
        assert "questions_or_comments_for_instructors" in message

    asyncio.run(scenario())


def test_application_tool_requires_supplied_form_categories_and_photo() -> None:
    assert CourseSubmitApplicationTool.input_schema["required"] == [
        "name",
        "email",
        "department_research_group_year_of_study_mit",
        "personal_webpage",
        "interests",
        "why_take_this_class",
        "knowledgeable_about",
        "skill_set",
        "registration_status",
        "listener_willing_to_do_weekly_builds",
        "questions_or_comments_for_instructors",
        "photo_upload_id",
    ]
    properties = CourseSubmitApplicationTool.input_schema["properties"]
    assert isinstance(properties, dict)
    registration_status = properties["registration_status"]
    assert isinstance(registration_status, dict)
    assert registration_status["enum"] == [
        "MAS student for credit",
        "MIT student for credit",
        "MAS student listener",
        "MIT student listener",
        "Other student for credit",
        "Other student listener",
    ]
