import pytest
from pydantic import SecretStr
from smolagents import OpenAIModel

from course_server.config import AgentSettings, ConfigurationError, MailSettings
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
    assert settings.published_faq_path.name == "published-faq.json"
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
            "PUBLISHED_FAQ_PATH": "/srv/class-agent/course-knowledge/published-faq.json",
        }
    )

    assert str(settings.course_data_path) == "/srv/class-agent/data"
    assert str(settings.skills_path) == "/srv/class-agent/skills"
    assert str(settings.applicant_data_path) == "/srv/class-agent/applicants"
    assert str(settings.upload_data_path) == "/srv/class-agent/uploads"
    assert str(settings.published_faq_path) == (
        "/srv/class-agent/course-knowledge/published-faq.json"
    )


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


def test_settings_load_optional_deployment_owned_outlook_configuration() -> None:
    environment = {
        "DATABASE_URL": "postgresql://example",
        "OPENAI_API_KEY": "test-secret-value",
        "BRAVE_API_KEY": "test-brave-value",
        "MAIL_ENABLED": "true",
        "MAIL_TENANT_ID": "tenant-id",
        "MAIL_CLIENT_ID": "client-id",
        "MAIL_CLIENT_SECRET": "mail-secret",
        "MAILBOX_ADDRESS": "course-agent@example.edu",
        "MAIL_STAFF_RECIPIENT_ADDRESS": "course-staff@example.edu",
        "MAIL_AUTHORIZED_REPLY_SENDERS": ("instructor@example.edu, teaching-assistant@example.edu"),
        "MAIL_POLL_INTERVAL_SECONDS": "45",
        "PUBLISHED_FAQ_PATH": "/srv/class-agent/course-knowledge/published-faq.json",
    }
    settings = AgentSettings.from_environment(environment)
    mail = MailSettings.optional_from_environment(environment)

    assert settings.mail_enabled
    assert mail is not None
    assert mail.provider == "microsoft_graph"
    assert str(mail.mailbox_address) == "course-agent@example.edu"
    assert str(mail.staff_recipient_address) == "course-staff@example.edu"
    assert mail.poll_interval_seconds == 45
    assert str(mail.published_faq_path) == ("/srv/class-agent/course-knowledge/published-faq.json")
    assert [str(value) for value in mail.authorized_reply_senders] == [
        "instructor@example.edu",
        "teaching-assistant@example.edu",
    ]
    assert "mail-secret" not in repr(mail)


def test_settings_load_optional_deployment_owned_gmail_configuration() -> None:
    environment = {
        "MAIL_ENABLED": "true",
        "MAIL_PROVIDER": "google_gmail",
        "MAIL_CLIENT_ID": "google-client-id",
        "MAIL_CLIENT_SECRET": "google-client-secret",
        "MAIL_REFRESH_TOKEN": "google-refresh-token",
        "MAILBOX_ADDRESS": "course-agent@example.edu",
        "MAIL_STAFF_RECIPIENT_ADDRESS": "course-staff@example.edu",
    }

    mail = MailSettings.optional_from_environment(environment)

    assert mail is not None
    assert mail.provider == "google_gmail"
    assert mail.tenant_id is None
    assert mail.refresh_token is not None
    assert mail.refresh_token.get_secret_value() == "google-refresh-token"
    assert "google-client-secret" not in repr(mail)
    assert "google-refresh-token" not in repr(mail)


def test_settings_require_complete_mail_configuration_only_when_enabled() -> None:
    with pytest.raises(ConfigurationError, match="MAIL_TENANT_ID"):
        MailSettings.optional_from_environment(
            {
                "MAIL_ENABLED": "true",
            }
        )

    with pytest.raises(ConfigurationError, match="MAIL_REFRESH_TOKEN"):
        MailSettings.optional_from_environment(
            {
                "MAIL_ENABLED": "true",
                "MAIL_PROVIDER": "google_gmail",
                "MAIL_CLIENT_ID": "client-id",
                "MAIL_CLIENT_SECRET": "client-secret",
                "MAILBOX_ADDRESS": "course-agent@example.edu",
                "MAIL_STAFF_RECIPIENT_ADDRESS": "course-staff@example.edu",
            }
        )


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
