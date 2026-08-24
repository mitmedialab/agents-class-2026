from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel

from agent_core import (
    AgentContext,
    AgentInput,
    AgentResult,
    Capability,
    Conversation,
    Event,
    Memory,
    Node,
    Permission,
    PrincipalContext,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "shared/schemas/v1/agent-core.schema.json"
EXAMPLES_PATH = PROJECT_ROOT / "shared/schemas/v1/examples/contracts.json"

CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "PrincipalContext": PrincipalContext,
    "Event": Event,
    "Conversation": Conversation,
    "Memory": Memory,
    "Capability": Capability,
    "Permission": Permission,
    "Node": Node,
    "AgentContext": AgentContext,
    "AgentInput": AgentInput,
    "AgentResult": AgentResult,
}


def load_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return cast(dict[str, Any], json.load(file))


SCHEMA = load_json_object(SCHEMA_PATH)
EXAMPLES = load_json_object(EXAMPLES_PATH)


def validator_for(contract_name: str) -> Draft202012Validator:
    wrapper = {
        "$schema": SCHEMA["$schema"],
        "$defs": SCHEMA["$defs"],
        "$ref": f"#/$defs/{contract_name}",
    }
    return Draft202012Validator(wrapper, format_checker=FormatChecker())


def test_canonical_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("contract_name", CONTRACT_MODELS)
def test_shared_examples_match_schema_and_python(
    contract_name: str,
) -> None:
    example = EXAMPLES[contract_name]
    validator_for(contract_name).validate(example)

    model = CONTRACT_MODELS[contract_name].model_validate(example)
    serialized = model.model_dump(mode="json")

    assert serialized == example
    validator_for(contract_name).validate(serialized)


def test_schema_rejects_unknown_event_fields() -> None:
    invalid_event = {**EXAMPLES["Event"], "unexpected": True}

    assert not validator_for("Event").is_valid(invalid_event)


def test_schema_rejects_anonymous_principal_with_student_role() -> None:
    invalid_principal = {
        "authenticated": False,
        "user_id": None,
        "anonymous_session_id": "90000000-0000-4000-8000-000000000001",
        "username": None,
        "display_name": None,
        "roles": ["public", "student"],
        "session_id": "90000000-0000-4000-8000-000000000002",
    }

    assert not validator_for("PrincipalContext").is_valid(invalid_principal)
