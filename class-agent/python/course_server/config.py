"""Environment-backed configuration for server-side adapters."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ConfigurationError(RuntimeError):
    """Required runtime configuration is absent or unsupported."""


class AgentSettings(BaseModel):
    """Configuration for the one global Course Agent definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: Literal["course-agent"] = "course-agent"
    agent_name: str = "Class Agent"
    runtime_id: Literal["smolagents-toolcalling"] = "smolagents-toolcalling"
    model_provider: Literal["openai"] = "openai"
    model_id: str = "gpt-5.6-terra"
    model_api_key: SecretStr = Field(repr=False)
    max_steps: int = Field(default=10, ge=1, le=50)
    database_url: str
    applicant_data_path: Path = Path(__file__).resolve().parents[2] / "var/applicants"
    upload_data_path: Path = Path(__file__).resolve().parents[2] / "var/uploads"
    browser_enabled: bool = True
    browser_max_sessions: int = Field(default=20, ge=1, le=100)
    browser_max_sessions_per_principal: int = Field(default=2, ge=1, le=10)
    browser_session_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    browser_executable_path: Path | None = None

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> AgentSettings:
        values = environment if environment is not None else os.environ
        provider = values.get("MODEL_PROVIDER", "openai").strip().casefold()
        if provider != "openai":
            raise ConfigurationError(f"unsupported MODEL_PROVIDER: {provider}")

        # MODEL_API_KEY is accepted for compatibility with the Phase 2 example.
        # OPENAI_API_KEY is the canonical name and is never written to history/logs.
        raw_api_key = values.get("OPENAI_API_KEY") or values.get("MODEL_API_KEY")
        if not raw_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required")
        api_key = raw_api_key.strip()
        if (
            not api_key
            or "\n" in api_key
            or "\r" in api_key
            or r"\n" in api_key
            or r"\r" in api_key
        ):
            raise ConfigurationError("OPENAI_API_KEY must be a non-empty single line")

        raw_database_url = values.get("DATABASE_URL")
        if not raw_database_url:
            raise ConfigurationError("DATABASE_URL is required")
        database_url = raw_database_url.strip()
        if not database_url:
            raise ConfigurationError("DATABASE_URL is required")

        model_id = values.get("MODEL_ID", "gpt-5.6-terra").strip()
        if not model_id:
            raise ConfigurationError("MODEL_ID must not be blank")

        raw_applicant_path = values.get("APPLICANT_DATA_PATH")
        applicant_data_path = (
            Path(raw_applicant_path.strip()).expanduser()
            if raw_applicant_path and raw_applicant_path.strip()
            else Path(__file__).resolve().parents[2] / "var/applicants"
        )
        raw_upload_path = values.get("UPLOAD_DATA_PATH")
        upload_data_path = (
            Path(raw_upload_path.strip()).expanduser()
            if raw_upload_path and raw_upload_path.strip()
            else Path(__file__).resolve().parents[2] / "var/uploads"
        )
        raw_browser_executable = values.get("BROWSER_EXECUTABLE_PATH")
        browser_executable_path = (
            Path(raw_browser_executable.strip()).expanduser()
            if raw_browser_executable and raw_browser_executable.strip()
            else None
        )
        browser_enabled = values.get("BROWSER_ENABLED", "true").strip().casefold()
        if browser_enabled not in {"true", "false", "1", "0", "yes", "no"}:
            raise ConfigurationError("BROWSER_ENABLED must be true or false")

        return cls(
            model_provider="openai",
            model_id=model_id,
            model_api_key=SecretStr(api_key),
            max_steps=int(values.get("AGENT_MAX_STEPS", "10")),
            database_url=database_url,
            applicant_data_path=applicant_data_path,
            upload_data_path=upload_data_path,
            browser_enabled=browser_enabled in {"true", "1", "yes"},
            browser_max_sessions=int(values.get("BROWSER_MAX_SESSIONS", "20")),
            browser_max_sessions_per_principal=int(
                values.get("BROWSER_MAX_SESSIONS_PER_PRINCIPAL", "2")
            ),
            browser_session_ttl_seconds=int(values.get("BROWSER_SESSION_TTL_SECONDS", "900")),
            browser_executable_path=browser_executable_path,
        )
