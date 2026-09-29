"""Canonical tool IDs for authenticated student-project inspection."""

LIST_STUDENT_PROJECTS_TOOL_ID = "course.list_student_projects"
INSPECT_STUDENT_SITE_TOOL_ID = "course.inspect_student_site"
INSPECT_STUDENT_REPOSITORY_TOOL_ID = "staff.inspect_student_repository"

STUDENT_PROJECT_TOOL_IDS = (
    LIST_STUDENT_PROJECTS_TOOL_ID,
    INSPECT_STUDENT_SITE_TOOL_ID,
)

READ_SHOWCASE_HISTORY_TOOL_ID = "staff.read_showcase_history"
SELECT_SHOWCASE_TOOL_ID = "staff.select_weekly_showcase"
SCREEN_SHOWCASE_TOOL_ID = "staff.screen_weekly_showcase"
SHOWCASE_IMAGES_TOOL_ID = "staff.discover_showcase_images"
SHOWCASE_TOOL_IDS = (
    SHOWCASE_IMAGES_TOOL_ID,
    READ_SHOWCASE_HISTORY_TOOL_ID,
    SELECT_SHOWCASE_TOOL_ID,
    SCREEN_SHOWCASE_TOOL_ID,
)
