"""Private, atomic weekly review/draw snapshots; presentation history stays staff-owned."""

from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from course_server.agent.capabilities import ToolValidationError

from .showcase import SelectionRequest, ShowcaseHistory, StrictModel, select_builds


class SelectionSnapshot(StrictModel):
    schema_version: Literal[1] = 1
    request: SelectionRequest
    history: ShowcaseHistory
    result: dict[str, JsonValue]


def read_snapshot(path: Path) -> SelectionSnapshot:
    try:
        if path.stat().st_size > 5_000_000:
            raise ValueError("snapshot too large")
        return SelectionSnapshot.model_validate_json(path.read_text())
    except (OSError, ValueError) as error:
        raise ToolValidationError(
            "Saved showcase review is invalid; ask staff to repair it."
        ) from error


def saved_selection(
    history_path: Path,
    request: SelectionRequest,
    history: ShowcaseHistory,
    sites: dict[str, str],
) -> tuple[dict[str, JsonValue], bool]:
    """Reuse the first validated review and draw, including across processes/restarts."""
    directory = history_path.parent / "selections"
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / f"week-{request.week:02d}.json"
        with (directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                saved = read_snapshot(path)
                if saved.request.week != request.week or saved.history != history:
                    raise ToolValidationError(
                        "Showcase history changed since the saved draw. Ask staff to archive "
                        "the week's selection snapshot before explicitly refreshing the review."
                    )
                pool = saved.request.eligible_projects or saved.request.candidates
                if any(p.project_id not in sites for p in pool):
                    raise ToolValidationError(
                        "Saved showcase contains a project no longer in the roster."
                    )
                result = dict(saved.result)
                result["sites"] = {p.project_id: sites[p.project_id] for p in pool}
                return result, True
            result = select_builds(request, history)
            pool = request.eligible_projects or request.candidates
            result["sites"] = {p.project_id: sites[p.project_id] for p in pool}
            snapshot = SelectionSnapshot(request=request, history=history, result=result)
            fd, temporary = tempfile.mkstemp(dir=directory, prefix=".selection-")
            try:
                with os.fdopen(fd, "w") as file:
                    file.write(snapshot.model_dump_json(indent=2))
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return result, False
    except OSError as error:
        raise ToolValidationError("The private showcase selection store is unavailable.") from error
