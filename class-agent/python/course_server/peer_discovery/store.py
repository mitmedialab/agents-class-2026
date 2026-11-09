"""Locked, atomic server files following the existing private showcase-store pattern.

Place this directory on persistent storage, outside public course resources. Each
student's file is named by trusted UUID. Public-source catalog is stored separately.
"""

import fcntl
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel

from .models import Catalog, StudentMemory

T = TypeVar("T", bound=BaseModel)


class PeerStore:
    def __init__(self, directory: Path):
        self.directory = directory

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _read(self, name: str, model: type[T]) -> T:
        path = self.directory / name
        if not path.exists():
            return model()
        if path.stat().st_size > 30_000_000:
            raise ValueError("Peer discovery data exceeds its storage limit.")
        return model.model_validate_json(path.read_text())

    def _write(self, name: str, value: BaseModel) -> None:
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix=".peer-")
        try:
            with os.fdopen(fd, "w") as file:
                file.write(value.model_dump_json(indent=2))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.directory / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def student(self, user: UUID) -> StudentMemory:
        with self._locked():
            return self._read(f"{user}.json", StudentMemory)

    def update_student(self, user: UUID, change: Callable[[StudentMemory], None]) -> StudentMemory:
        with self._locked():
            state = self._read(f"{user}.json", StudentMemory)
            change(state)
            self._write(f"{user}.json", state)
            return state

    def forget(self, user: UUID) -> None:
        with self._locked():
            (self.directory / f"{user}.json").unlink(missing_ok=True)

    def catalog(self) -> Catalog:
        with self._locked():
            return self._read("catalog.json", Catalog)

    def update_catalog(self, change: Callable[[Catalog], None]) -> Catalog:
        with self._locked():
            catalog = self._read("catalog.json", Catalog)
            change(catalog)
            if len(catalog.builds) > 600:
                raise ValueError("Peer catalog limit reached; refresh existing records instead.")
            self._write("catalog.json", catalog)
            return catalog
