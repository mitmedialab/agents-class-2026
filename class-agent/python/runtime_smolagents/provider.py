"""OpenAI model adapter used by the smolagents runtime."""

from dataclasses import dataclass

from pydantic import SecretStr
from smolagents import Model, OpenAIModel


@dataclass(frozen=True)
class OpenAIModelProvider:
    """Creates transient smolagents OpenAI models from server-side secrets."""

    model_id: str
    api_key: SecretStr
    provider_id: str = "openai"
    api_base: str = "https://api.openai.com/v1"

    def create_model(self) -> Model:
        return OpenAIModel(
            model_id=self.model_id,
            api_base=self.api_base,
            api_key=self.api_key.get_secret_value(),
            # smolagents 1.x uses Chat Completions. GPT-5.6 Terra accepts
            # function tools on that endpoint only when reasoning is disabled.
            reasoning_effort="none",
        )
