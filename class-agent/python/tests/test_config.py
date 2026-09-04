import pytest
from pydantic import SecretStr
from smolagents import OpenAIModel

from course_server.config import AgentSettings, ConfigurationError
from runtime_smolagents import OpenAIModelProvider


def test_settings_accept_standard_openai_environment_without_exposing_secret() -> None:
    settings = AgentSettings.from_environment(
        {
            "DATABASE_URL": "postgresql://example",
            "OPENAI_API_KEY": "  test-secret-value\n\n",
            "BRAVE_API_KEY": "  test-brave-value\n\n",
            "MODEL_ID": "test-model",
        }
    )

    assert settings.model_id == "test-model"
    assert settings.model_api_key.get_secret_value() == "test-secret-value"
    assert settings.brave_search_api_key.get_secret_value() == "test-brave-value"
    assert settings.course_data_path.name == "data"
    assert settings.skills_path.name == "skills"
    assert settings.applicant_data_path.name == "applicants"
    assert settings.upload_data_path.name == "uploads"
    assert settings.browser_enabled is True
    assert settings.browser_max_sessions == 20
    assert settings.browser_max_sessions_per_principal == 2
    assert settings.anonymous_quotas_enabled is True
    assert "test-secret-value" not in repr(settings)
    assert "test-brave-value" not in repr(settings)


def test_settings_accept_private_applicant_storage_path() -> None:
    settings = AgentSettings.from_environment(
        {
            "DATABASE_URL": "postgresql://example",
            "OPENAI_API_KEY": "test-secret-value",
            "BRAVE_API_KEY": "test-brave-value",
            "COURSE_DATA_PATH": "/srv/class-agent/data",
            "SKILLS_PATH": "/srv/class-agent/skills",
            "APPLICANT_DATA_PATH": "/srv/class-agent/applicants",
            "UPLOAD_DATA_PATH": "/srv/class-agent/uploads",
        }
    )

    assert str(settings.course_data_path) == "/srv/class-agent/data"
    assert str(settings.skills_path) == "/srv/class-agent/skills"
    assert str(settings.applicant_data_path) == "/srv/class-agent/applicants"
    assert str(settings.upload_data_path) == "/srv/class-agent/uploads"


def test_settings_can_disable_and_bound_the_remote_browser() -> None:
    settings = AgentSettings.from_environment(
        {
            "DATABASE_URL": "postgresql://example",
            "OPENAI_API_KEY": "test-secret-value",
            "BRAVE_API_KEY": "test-brave-value",
            "BROWSER_ENABLED": "false",
            "BROWSER_MAX_SESSIONS": "12",
            "BROWSER_MAX_SESSIONS_PER_PRINCIPAL": "1",
            "BROWSER_SESSION_TTL_SECONDS": "600",
            "BROWSER_EXECUTABLE_PATH": "/opt/chromium/chrome",
        }
    )

    assert settings.browser_enabled is False
    assert settings.browser_max_sessions == 12
    assert settings.browser_max_sessions_per_principal == 1
    assert settings.browser_session_ttl_seconds == 600
    assert str(settings.browser_executable_path) == "/opt/chromium/chrome"


def test_settings_can_disable_strict_workspace_visual_policy() -> None:
    settings = AgentSettings.from_environment(
        {
            "DATABASE_URL": "postgresql://example",
            "OPENAI_API_KEY": "test-secret-value",
            "BRAVE_API_KEY": "test-brave-value",
            "WORKSPACE_STRICT_VISUAL_POLICY": "false",
        }
    )

    assert settings.workspace_strict_visual_policy is False


def test_settings_can_disable_anonymous_quotas_for_local_development() -> None:
    settings = AgentSettings.from_environment(
        {
            "DATABASE_URL": "postgresql://example",
            "OPENAI_API_KEY": "test-secret-value",
            "BRAVE_API_KEY": "test-brave-value",
            "ANONYMOUS_QUOTAS_ENABLED": "false",
        }
    )

    assert settings.anonymous_quotas_enabled is False


def test_openai_provider_creates_transient_smolagents_model_without_network_call() -> None:
    provider = OpenAIModelProvider(
        model_id="test-model",
        api_key=SecretStr("test-secret-value"),
    )

    assert provider.provider_id == "openai"
    assert provider.model_id == "test-model"
    assert "test-secret-value" not in repr(provider)
    model = provider.create_model()
    assert isinstance(model, OpenAIModel)
    assert model.model_id == "test-model"
    assert model.kwargs["reasoning_effort"] == "none"


def test_settings_reject_embedded_api_key_line_breaks() -> None:
    with pytest.raises(ConfigurationError, match="single line"):
        AgentSettings.from_environment(
            {
                "DATABASE_URL": "postgresql://example",
                "OPENAI_API_KEY": "first-line\nsecond-line",
                "BRAVE_API_KEY": "test-brave-value",
            }
        )


@pytest.mark.parametrize("line_break", [r"\n", r"\r"])
def test_settings_reject_literal_api_key_line_break_sequences(line_break: str) -> None:
    with pytest.raises(ConfigurationError, match="single line"):
        AgentSettings.from_environment(
            {
                "DATABASE_URL": "postgresql://example",
                "OPENAI_API_KEY": f"test-secret-value{line_break}",
                "BRAVE_API_KEY": "test-brave-value",
            }
        )


def test_settings_require_brave_search_api_key() -> None:
    with pytest.raises(ConfigurationError, match="BRAVE_API_KEY is required"):
        AgentSettings.from_environment(
            {
                "DATABASE_URL": "postgresql://example",
                "OPENAI_API_KEY": "test-secret-value",
            }
        )


@pytest.mark.parametrize("line_break", ["\n", "\r", r"\n", r"\r"])
def test_settings_reject_brave_api_key_line_breaks(line_break: str) -> None:
    with pytest.raises(ConfigurationError, match=r"BRAVE_API_KEY.*single line"):
        AgentSettings.from_environment(
            {
                "DATABASE_URL": "postgresql://example",
                "OPENAI_API_KEY": "test-secret-value",
                "BRAVE_API_KEY": f"test-brave-value{line_break}suffix",
            }
        )
