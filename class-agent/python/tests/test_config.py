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
            "MODEL_ID": "test-model",
        }
    )

    assert settings.model_id == "test-model"
    assert settings.model_api_key.get_secret_value() == "test-secret-value"
    assert "test-secret-value" not in repr(settings)


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
            }
        )


@pytest.mark.parametrize("line_break", [r"\n", r"\r"])
def test_settings_reject_literal_api_key_line_break_sequences(line_break: str) -> None:
    with pytest.raises(ConfigurationError, match="single line"):
        AgentSettings.from_environment(
            {
                "DATABASE_URL": "postgresql://example",
                "OPENAI_API_KEY": f"test-secret-value{line_break}",
            }
        )
