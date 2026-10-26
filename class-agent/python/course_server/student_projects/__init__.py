"""Read-only GitHub-backed student project capabilities."""

from course_server.student_project_tool_ids import (
    INSPECT_MY_STUDENT_REPOSITORY_TOOL_ID,
    INSPECT_MY_STUDENT_SITE_TOOL_ID,
    INSPECT_STUDENT_REPOSITORY_TOOL_ID,
    INSPECT_STUDENT_SITE_TOOL_ID,
    LIST_STUDENT_PROJECTS_TOOL_ID,
    OWN_STUDENT_PROJECT_TOOL_IDS,
    STUDENT_PROJECT_TOOL_IDS,
)

from .client import (
    GitHubStudentProjectCatalog,
    RepositoryView,
    StudentProject,
    StudentProjectCatalog,
    StudentProjectNotFound,
    StudentProjectProviderError,
)
from .tools import (
    InspectMyStudentRepositoryTool,
    InspectMyStudentSiteTool,
    InspectStudentRepositoryTool,
    InspectStudentSiteTool,
    ListStudentProjectsTool,
)

__all__ = [
    "INSPECT_MY_STUDENT_REPOSITORY_TOOL_ID",
    "INSPECT_MY_STUDENT_SITE_TOOL_ID",
    "INSPECT_STUDENT_REPOSITORY_TOOL_ID",
    "INSPECT_STUDENT_SITE_TOOL_ID",
    "LIST_STUDENT_PROJECTS_TOOL_ID",
    "OWN_STUDENT_PROJECT_TOOL_IDS",
    "STUDENT_PROJECT_TOOL_IDS",
    "GitHubStudentProjectCatalog",
    "InspectMyStudentRepositoryTool",
    "InspectMyStudentSiteTool",
    "InspectStudentRepositoryTool",
    "InspectStudentSiteTool",
    "ListStudentProjectsTool",
    "RepositoryView",
    "StudentProject",
    "StudentProjectCatalog",
    "StudentProjectNotFound",
    "StudentProjectProviderError",
]
