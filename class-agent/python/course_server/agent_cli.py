"""CLI-first Phase 3 entry point for one anonymous Course Agent turn."""

from __future__ import annotations

import argparse
import asyncio
import re
from collections.abc import Sequence

from dotenv import load_dotenv

from agent_core import AgentResult, AgentRuntime, Conversation
from course_server.agent import (
    CourseAgentService,
    CourseReadSyllabusTool,
    FileResourceProvider,
    ToolCatalog,
)
from course_server.agent.store import ConversationStore
from course_server.auth import AuthenticationService
from course_server.auth.store import AuthStore
from course_server.config import AgentSettings, ConfigurationError
from course_server.migrations import apply_migrations
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool
from course_server.postgres.conversation_store import PostgresConversationStore
from runtime_smolagents import OpenAIModelProvider, SmolagentsRuntime

_SAFE_PROVIDER_FIELD = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,120}$")


async def run_cli_turn(
    text: str,
    *,
    runtime: AgentRuntime,
    auth_store: AuthStore,
    conversation_store: ConversationStore,
) -> tuple[Conversation, AgentResult]:
    """Run the CLI flow with injectable adapters so tests never call an external model."""

    authentication = AuthenticationService(auth_store)
    credential = await authentication.create_anonymous()
    principal = await authentication.resolve_anonymous(credential.token)
    service = CourseAgentService(runtime=runtime, conversations=conversation_store)
    conversation = await service.create_conversation(principal)
    result = await service.run(
        principal=principal,
        conversation_id=conversation.id,
        text=text,
    )
    return conversation, result


def build_runtime(settings: AgentSettings) -> SmolagentsRuntime:
    resources = FileResourceProvider.with_sample_syllabus()
    tools = ToolCatalog([CourseReadSyllabusTool(resources)])
    provider = OpenAIModelProvider(
        model_id=settings.model_id,
        api_key=settings.model_api_key,
    )
    return SmolagentsRuntime(
        model_provider=provider,
        tools=tools,
        max_steps=settings.max_steps,
        agent_id=settings.agent_id,
    )


async def _run_postgres_turn(
    text: str,
    settings: AgentSettings,
) -> tuple[Conversation, AgentResult]:
    pool = create_auth_pool(settings.database_url)
    await pool.open()
    await pool.wait()
    try:
        return await run_cli_turn(
            text,
            runtime=build_runtime(settings),
            auth_store=PostgresAuthStore(pool),
            conversation_store=PostgresConversationStore(pool),
        )
    finally:
        await pool.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one Class Agent CLI turn")
    parser.add_argument("message", help="message to send to the Course Agent")
    return parser


def _exception_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(chain) < 5:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _safe_provider_details(chain: Sequence[BaseException]) -> str:
    for error in chain:
        status_code = getattr(error, "status_code", None)
        if not isinstance(status_code, int):
            continue
        fields = [f"status={status_code}"]
        for name in ("type", "code", "param"):
            value = getattr(error, name, None)
            if isinstance(value, str) and _SAFE_PROVIDER_FIELD.fullmatch(value):
                fields.append(f"{name}={value}")
        return ", ".join(fields)
    return ""


def _safe_failure_message(error: Exception) -> str:
    chain = _exception_chain(error)
    type_chain = " <- ".join(type(item).__name__ for item in chain)
    provider_details = _safe_provider_details(chain)
    detail_suffix = f" [{provider_details}]" if provider_details else ""
    return (
        f"Class Agent failed ({type_chain}){detail_suffix}. "
        "Check the database, model name, API key, and network connection."
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    load_dotenv(override=False)
    try:
        settings = AgentSettings.from_environment()
    except (ConfigurationError, ValueError) as error:
        raise SystemExit(f"Configuration error: {error}") from error

    try:
        apply_migrations(settings.database_url)
        conversation, result = asyncio.run(_run_postgres_turn(arguments.message, settings))
    except Exception as error:
        raise SystemExit(_safe_failure_message(error)) from None
    print(result.output_text)
    print(f"\nConversation: {conversation.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
