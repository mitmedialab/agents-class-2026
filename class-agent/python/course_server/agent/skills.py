"""Standard Agent Skill loading with principal-scoped authorization."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from agent_core import PrincipalContext

from .capabilities import ToolExecutionContext, ToolExecutionResult, ToolValidationError

READ_SKILL_TOOL_ID = "skills.read"
READ_SKILL_REFERENCE_TOOL_ID = "skills.read_reference"

SkillAudience = Literal["public", "authenticated", "students", "instructors"]

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(?P<yaml>.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_MAX_SKILL_FILE_BYTES = 64 * 1024
_MAX_SKILL_FRONTMATTER_CHARACTERS = 16 * 1024
_MAX_REFERENCE_FILE_BYTES = 128 * 1024
_MAX_REFERENCES_PER_SKILL = 64
_MAX_SKILL_ID_LENGTH = 64
_MAX_REFERENCE_PATH_LENGTH = 240


class SkillCatalogError(RuntimeError):
    """A repository-owned skill or authorization entry is invalid."""


class SkillRegistryEntry(BaseModel):
    """Authorization metadata kept separate from a standard skill bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=_MAX_SKILL_ID_LENGTH)
    directory: str = Field(min_length=1, max_length=_MAX_REFERENCE_PATH_LENGTH)
    audience: SkillAudience = "public"

    @field_validator("directory")
    @classmethod
    def validate_directory(cls, value: str) -> str:
        _validate_relative_path(value, field_name="skill directory")
        return value


class SkillRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    skills: list[SkillRegistryEntry]


class SkillFrontmatter(BaseModel):
    """Required fields from the open Agent Skills SKILL.md format."""

    model_config = ConfigDict(extra="allow", frozen=True)

    name: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=_MAX_SKILL_ID_LENGTH)
    description: str = Field(min_length=1, max_length=1_024)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("skill description must not be blank")
        return normalized


class SkillMetadata(BaseModel):
    """Path-free metadata safe to disclose to an authorized model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    description: str
    audience: SkillAudience


@dataclass(frozen=True)
class _SkillDefinition:
    metadata: SkillMetadata
    skill_path: Path
    directory: Path
    references: tuple[str, ...]


@dataclass(frozen=True)
class _SkillDocument:
    metadata: SkillMetadata
    instructions: str
    references: tuple[str, ...]


def _validate_relative_path(value: str, *, field_name: str) -> PurePosixPath:
    if "\\" in value:
        raise ValueError(f"{field_name} must use forward slashes")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{field_name} must be a normalized relative path")
    return path


def _confined_path(root: Path, relative: str, *, field_name: str) -> Path:
    relative_path = _validate_relative_path(relative, field_name=field_name)
    candidate = root.joinpath(*relative_path.parts).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"{field_name} escapes its registered root")
    return candidate


def _read_bounded_text(path: Path, *, maximum_bytes: int, label: str) -> str:
    try:
        size = path.stat().st_size
        if not path.is_file() or size > maximum_bytes:
            raise SkillCatalogError(f"{label} is missing or exceeds {maximum_bytes} bytes")
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise SkillCatalogError(f"could not read {label}") from error
    except UnicodeDecodeError as error:
        raise SkillCatalogError(f"{label} must be UTF-8 text") from error


def _read_skill_prefix(path: Path, entry: SkillRegistryEntry) -> str:
    label = f"skill {entry.id}"
    try:
        size = path.stat().st_size
        if not path.is_file() or size > _MAX_SKILL_FILE_BYTES:
            raise SkillCatalogError(f"{label} is missing or exceeds {_MAX_SKILL_FILE_BYTES} bytes")
        with path.open(encoding="utf-8") as skill_file:
            return skill_file.read(_MAX_SKILL_FRONTMATTER_CHARACTERS)
    except OSError as error:
        raise SkillCatalogError(f"could not read {label} metadata") from error
    except UnicodeDecodeError as error:
        raise SkillCatalogError(f"{label} must be UTF-8 text") from error


def _parse_frontmatter(text: str, skill_id: str) -> tuple[SkillFrontmatter, int]:
    match = _FRONTMATTER.match(text)
    if match is None:
        raise SkillCatalogError(f"skill {skill_id} requires bounded YAML frontmatter")
    try:
        raw_frontmatter = yaml.safe_load(match.group("yaml"))
        frontmatter = SkillFrontmatter.model_validate(raw_frontmatter)
    except (yaml.YAMLError, ValidationError) as error:
        raise SkillCatalogError(f"skill {skill_id} has invalid frontmatter") from error
    return frontmatter, match.end()


def _scan_skill_metadata(path: Path, entry: SkillRegistryEntry) -> SkillFrontmatter:
    frontmatter, _ = _parse_frontmatter(_read_skill_prefix(path, entry), entry.id)
    if frontmatter.name != entry.id:
        raise SkillCatalogError(f"skill registry ID {entry.id} must match SKILL.md name")
    return frontmatter


def _load_skill_document(definition: _SkillDefinition) -> _SkillDocument:
    text = _read_bounded_text(
        definition.skill_path,
        maximum_bytes=_MAX_SKILL_FILE_BYTES,
        label=f"skill {definition.metadata.id}",
    )
    frontmatter, body_start = _parse_frontmatter(text, definition.metadata.id)
    if (
        frontmatter.name != definition.metadata.name
        or frontmatter.description != definition.metadata.description
    ):
        raise SkillCatalogError(
            f"skill {definition.metadata.id} metadata changed; restart the application"
        )
    instructions = text[body_start:].strip()
    if not instructions:
        raise SkillCatalogError(f"skill {definition.metadata.id} has no instructions")
    return _SkillDocument(
        metadata=definition.metadata,
        instructions=instructions,
        references=definition.references,
    )


def _visible_to_principal(audience: SkillAudience, principal: PrincipalContext) -> bool:
    if audience == "public":
        return True
    if not principal.authenticated:
        return False
    if audience == "authenticated":
        return True
    if audience == "students":
        return "student" in principal.roles or "instructor" in principal.roles
    return audience == "instructors" and "instructor" in principal.roles


class SkillCatalog:
    """Startup-scanned standard skills with deterministic audience filtering."""

    def __init__(self, definitions: list[_SkillDefinition]) -> None:
        self._skills = {definition.metadata.id: definition for definition in definitions}
        if len(self._skills) != len(definitions):
            raise SkillCatalogError("skill IDs must be unique")

    @classmethod
    def from_registry(cls, skills_root: Path) -> SkillCatalog:
        root = skills_root.resolve()
        registry_path = root / "registry.json"
        try:
            registry = SkillRegistry.model_validate_json(registry_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise SkillCatalogError("skill authorization registry is missing or invalid") from error

        definitions: list[_SkillDefinition] = []
        seen_directories: set[Path] = set()
        for entry in registry.skills:
            if PurePosixPath(entry.directory).name != entry.id:
                raise SkillCatalogError(
                    f"skill {entry.id} directory name must match its standard skill name"
                )
            registered_directory = root.joinpath(*PurePosixPath(entry.directory).parts)
            if registered_directory.is_symlink():
                raise SkillCatalogError(f"skill {entry.id} directory must not be a symlink")
            try:
                directory = _confined_path(root, entry.directory, field_name="skill directory")
            except ValueError as error:
                raise SkillCatalogError(f"skill {entry.id} has an invalid directory") from error
            if directory in seen_directories:
                raise SkillCatalogError("skill directories must be unique")
            seen_directories.add(directory)
            registered_skill_path = directory / "SKILL.md"
            if registered_skill_path.is_symlink():
                raise SkillCatalogError(f"skill {entry.id} SKILL.md must not be a symlink")
            skill_path = registered_skill_path.resolve()
            if not skill_path.is_relative_to(directory):
                raise SkillCatalogError(f"skill {entry.id} has an unconfined SKILL.md")
            frontmatter = _scan_skill_metadata(skill_path, entry)

            reference_root = directory / "references"
            references: list[str] = []
            if reference_root.is_dir():
                if reference_root.is_symlink():
                    raise SkillCatalogError(
                        f"skill {entry.id} reference directory must not be a symlink"
                    )
                resolved_reference_root = reference_root.resolve()
                if not resolved_reference_root.is_relative_to(directory):
                    raise SkillCatalogError(f"skill {entry.id} has an unconfined reference root")
                for reference_path in sorted(reference_root.rglob("*.md")):
                    if reference_path.is_symlink():
                        raise SkillCatalogError(
                            f"skill {entry.id} reference files must not be symlinks"
                        )
                    resolved_reference = reference_path.resolve()
                    if not resolved_reference.is_relative_to(resolved_reference_root):
                        raise SkillCatalogError(f"skill {entry.id} has an unconfined reference")
                    references.append(resolved_reference.relative_to(directory).as_posix())
                    if len(references) > _MAX_REFERENCES_PER_SKILL:
                        raise SkillCatalogError(f"skill {entry.id} has too many references")

            definitions.append(
                _SkillDefinition(
                    metadata=SkillMetadata(
                        id=entry.id,
                        name=frontmatter.name,
                        description=frontmatter.description.strip(),
                        audience=entry.audience,
                    ),
                    skill_path=skill_path,
                    directory=directory,
                    references=tuple(references),
                )
            )
        return cls(definitions)

    def authorized_metadata(self, principal: PrincipalContext) -> tuple[SkillMetadata, ...]:
        return tuple(
            definition.metadata
            for definition in self._skills.values()
            if _visible_to_principal(definition.metadata.audience, principal)
        )

    def _authorized_definition(
        self,
        skill_id: str,
        principal: PrincipalContext,
    ) -> _SkillDefinition:
        definition = self._skills.get(skill_id)
        if definition is None or not _visible_to_principal(definition.metadata.audience, principal):
            raise PermissionError("skill is not available to this principal")
        return definition

    def read_skill(self, skill_id: str, principal: PrincipalContext) -> _SkillDocument:
        return _load_skill_document(self._authorized_definition(skill_id, principal))

    def read_reference(
        self,
        skill_id: str,
        reference_path: str,
        principal: PrincipalContext,
    ) -> str:
        definition = self._authorized_definition(skill_id, principal)
        try:
            normalized_path = _validate_relative_path(reference_path, field_name="reference_path")
        except ValueError as error:
            raise ToolValidationError(str(error)) from error
        normalized = normalized_path.as_posix()
        if normalized not in definition.references:
            raise PermissionError("skill reference is not registered")
        path = _confined_path(definition.directory, normalized, field_name="reference_path")
        return _read_bounded_text(
            path,
            maximum_bytes=_MAX_REFERENCE_FILE_BYTES,
            label=f"skill {skill_id} reference",
        )


def _required_string_argument(
    arguments: Mapping[str, JsonValue],
    field: str,
    *,
    maximum_length: int,
) -> str:
    value = arguments.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ToolValidationError(f"{field} must be non-empty text")
    normalized = value.strip()
    if len(normalized) > maximum_length:
        raise ToolValidationError(f"{field} is too long")
    return normalized


class ReadSkillTool:
    """Load a complete authorized SKILL.md body only when the task requires it."""

    id = READ_SKILL_TOOL_ID
    description = (
        "Load the full instructions for one authorized skill when its metadata matches the task. "
        "Use an exact skill_id from the available skill metadata."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "Exact authorized skill ID advertised in the system context.",
                "minLength": 1,
                "maxLength": _MAX_SKILL_ID_LENGTH,
            }
        },
        "required": ["skill_id"],
        "additionalProperties": False,
    }

    def __init__(self, skills: SkillCatalog) -> None:
        self._skills = skills

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if set(arguments) != {"skill_id"}:
            raise ToolValidationError("skill_id is required and no other fields are accepted")
        skill_id = _required_string_argument(
            arguments,
            "skill_id",
            maximum_length=_MAX_SKILL_ID_LENGTH,
        )
        definition = self._skills.read_skill(skill_id, context.principal)
        raw_loaded_skill_ids = context.transient_state.setdefault("loaded_skill_ids", [])
        loaded_skill_ids = raw_loaded_skill_ids if isinstance(raw_loaded_skill_ids, list) else []
        if loaded_skill_ids is not raw_loaded_skill_ids:
            context.transient_state["loaded_skill_ids"] = loaded_skill_ids
        if skill_id not in loaded_skill_ids:
            loaded_skill_ids.append(skill_id)
        return ToolExecutionResult(
            content={
                "skill_id": skill_id,
                "instructions": definition.instructions,
                "references": list(definition.references),
            },
            summary=f"Loaded authorized skill {skill_id}.",
            storage_policy="server_summary",
        )


class ReadSkillReferenceTool:
    """Load one registered reference from an already relevant authorized skill."""

    id = READ_SKILL_REFERENCE_TOOL_ID
    description = (
        "Load one reference listed by skills.read when that extra detail is needed. "
        "Both the skill and reference are re-authorized from the trusted login context."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "Exact authorized skill ID previously loaded with skills.read.",
                "minLength": 1,
                "maxLength": _MAX_SKILL_ID_LENGTH,
            },
            "reference_path": {
                "type": "string",
                "description": "Exact relative reference path returned by skills.read.",
                "minLength": 1,
                "maxLength": _MAX_REFERENCE_PATH_LENGTH,
            },
        },
        "required": ["skill_id", "reference_path"],
        "additionalProperties": False,
    }

    def __init__(self, skills: SkillCatalog) -> None:
        self._skills = skills

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if set(arguments) != {"skill_id", "reference_path"}:
            raise ToolValidationError(
                "skill_id and reference_path are required and no other fields are accepted"
            )
        skill_id = _required_string_argument(
            arguments,
            "skill_id",
            maximum_length=_MAX_SKILL_ID_LENGTH,
        )
        reference_path = _required_string_argument(
            arguments,
            "reference_path",
            maximum_length=_MAX_REFERENCE_PATH_LENGTH,
        )
        loaded_skill_ids = context.transient_state.get("loaded_skill_ids")
        if not isinstance(loaded_skill_ids, list) or skill_id not in loaded_skill_ids:
            raise PermissionError("skill must be loaded before reading one of its references")
        content = self._skills.read_reference(skill_id, reference_path, context.principal)
        return ToolExecutionResult(
            content={
                "skill_id": skill_id,
                "reference_path": reference_path,
                "content": content,
            },
            summary=f"Loaded an authorized reference for skill {skill_id}.",
            storage_policy="server_summary",
        )
