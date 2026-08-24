"""Agent runtime boundary owned by the platform rather than a framework."""

from typing import Protocol, runtime_checkable

from .models import AgentContext, AgentInput, AgentResult


@runtime_checkable
class AgentRuntime(Protocol):
    """Adapter interface implemented by concrete agent runtimes."""

    async def run(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
    ) -> AgentResult:
        """Run the agent with trusted context and portable input."""
        ...
