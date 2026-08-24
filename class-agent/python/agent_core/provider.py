"""Model-provider boundary independent of any agent framework."""

from typing import Protocol, TypeVar, runtime_checkable

RuntimeModel = TypeVar("RuntimeModel", covariant=True)


@runtime_checkable
class ModelProvider(Protocol[RuntimeModel]):
    """Creates a transient runtime model without making it persistent state."""

    @property
    def provider_id(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    def create_model(self) -> RuntimeModel: ...
