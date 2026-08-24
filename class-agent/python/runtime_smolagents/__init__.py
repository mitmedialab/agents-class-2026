"""smolagents adapter for the application-owned runtime interfaces."""

from .provider import OpenAIModelProvider
from .runtime import SmolagentsRuntime

__all__ = ["OpenAIModelProvider", "SmolagentsRuntime"]
