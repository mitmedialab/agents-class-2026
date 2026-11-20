"""Canonical tool IDs for the course-improvement loop and the phase that may use each."""

from course_server.agent.capabilities import (
    ASK_TA_TOOL_ID,
    COURSE_GET_ASSIGNMENT_TOOL_ID,
    COURSE_INSPECT_SLIDE_PAGE_TOOL_ID,
    COURSE_LIST_ASSIGNMENTS_TOOL_ID,
    DOCUMENT_INSPECT_PAGE_TOOL_ID,
    GET_APPLICATION_TOOL_ID,
    GET_MY_GRADES_TOOL_ID,
    GET_SCHEDULE_TOOL_ID,
    INSTRUCTOR_INSPECT_APPLICATION_IMAGES_TOOL_ID,
    INSTRUCTOR_LIST_APPLICATIONS_TOOL_ID,
    INSTRUCTOR_LIST_STUDENTS_TOOL_ID,
    INSTRUCTOR_MESSAGE_STUDENTS_TOOL_ID,
    INSTRUCTOR_READ_APPLICATION_TOOL_ID,
    LIST_FAQ_UPDATES_TOOL_ID,
    LIST_MY_COMMUNICATIONS_TOOL_ID,
    LIST_PRIVATE_RESOURCES_TOOL_ID,
    READ_FAQ_UPDATE_TOOL_ID,
    READ_MY_COMMUNICATION_TOOL_ID,
    READ_PRIVATE_RESOURCE_TOOL_ID,
    READ_PUBLIC_FILE_TOOL_ID,
    READ_SYLLABUS_TOOL_ID,
    READ_UPLOAD_TOOL_ID,
    SEARCH_COURSE_TOOL_ID,
    SEARCH_FAQ_TOOL_ID,
    SHOW_PUBLIC_FILES_TOOL_ID,
    SUBMIT_APPLICATION_TOOL_ID,
    VISIT_WEBPAGE_TOOL_ID,
    WEB_IMAGE_INSPECT_TOOL_ID,
    WEB_IMAGE_SEARCH_TOOL_ID,
    WEB_SEARCH_TOOL_ID,
)
from course_server.agent.skills import READ_SKILL_REFERENCE_TOOL_ID, READ_SKILL_TOOL_ID
from course_server.browser import constants as browser_tools
from course_server.student_project_tool_ids import (
    INSPECT_MY_STUDENT_REPOSITORY_TOOL_ID,
    INSPECT_MY_STUDENT_SITE_TOOL_ID,
    INSPECT_STUDENT_REPOSITORY_TOOL_ID,
    INSPECT_STUDENT_SITE_TOOL_ID,
    LIST_STUDENT_PROJECTS_TOOL_ID,
    READ_SHOWCASE_HISTORY_TOOL_ID,
    SCREEN_SHOWCASE_TOOL_ID,
    SELECT_SHOWCASE_TOOL_ID,
    SHOWCASE_IMAGES_TOOL_ID,
)
from course_server.workspace import constants as workspace_tools

from .models import LoopPhase

READ_BRIEF_TOOL_ID = "improvement.read_brief"
NOTE_FINDING_TOOL_ID = "improvement.note_finding"
PROPOSE_CHANGE_TOOL_ID = "improvement.propose_change"
REVISE_PROPOSAL_TOOL_ID = "improvement.revise_proposal"
SUBMIT_CRITIQUE_TOOL_ID = "improvement.submit_critique"
SCORE_REPLAY_TOOL_ID = "improvement.score_replay"
RANK_PROPOSALS_TOOL_ID = "improvement.rank_proposals"
COMPACT_NOTEBOOK_TOOL_ID = "improvement.compact_notebook"

# Trusted allowlist: each phase can write exactly one kind of record, so an author run cannot
# critique its own proposal and no run can score, rank, or approve outside its phase.
# No tool approves, rejects, or retires a proposal.
PHASE_WRITE_TOOL_IDS: dict[LoopPhase, tuple[str, ...]] = {
    "research": (READ_BRIEF_TOOL_ID, NOTE_FINDING_TOOL_ID),
    "propose": (READ_BRIEF_TOOL_ID, PROPOSE_CHANGE_TOOL_ID),
    "replay": (SCORE_REPLAY_TOOL_ID,),
    # The simulated student only writes its next message; the loop records the transcript.
    "trial": (),
    "critique": (READ_BRIEF_TOOL_ID, SUBMIT_CRITIQUE_TOOL_ID),
    "revise": (READ_BRIEF_TOOL_ID, REVISE_PROPOSAL_TOOL_ID),
    "rank": (READ_BRIEF_TOOL_ID, RANK_PROPOSALS_TOOL_ID),
    "compact": (READ_BRIEF_TOOL_ID, COMPACT_NOTEBOOK_TOOL_ID),
}
# Phases in which the Course Agent chooses for itself among the read tools below. Replay
# scoring, ranking, and compaction work only from the brief.
READ_PHASES: frozenset[LoopPhase] = frozenset({"research", "propose", "critique", "revise"})

# Trusted allowlist: every Course Agent tool that only reads course material, student
# projects, skills, or the public web. The loop offers a read phase whichever of these the
# capability policy also authorizes for the instructor; the agent decides what it needs.
LOOP_READ_TOOL_IDS: frozenset[str] = frozenset(
    {
        READ_SYLLABUS_TOOL_ID,
        READ_PUBLIC_FILE_TOOL_ID,
        SHOW_PUBLIC_FILES_TOOL_ID,
        GET_SCHEDULE_TOOL_ID,
        GET_APPLICATION_TOOL_ID,
        COURSE_LIST_ASSIGNMENTS_TOOL_ID,
        COURSE_GET_ASSIGNMENT_TOOL_ID,
        SEARCH_COURSE_TOOL_ID,
        SEARCH_FAQ_TOOL_ID,
        COURSE_INSPECT_SLIDE_PAGE_TOOL_ID,
        LIST_PRIVATE_RESOURCES_TOOL_ID,
        READ_PRIVATE_RESOURCE_TOOL_ID,
        LIST_STUDENT_PROJECTS_TOOL_ID,
        INSPECT_STUDENT_SITE_TOOL_ID,
        INSPECT_STUDENT_REPOSITORY_TOOL_ID,
        READ_SHOWCASE_HISTORY_TOOL_ID,
        SCREEN_SHOWCASE_TOOL_ID,
        SHOWCASE_IMAGES_TOOL_ID,
        READ_SKILL_TOOL_ID,
        READ_SKILL_REFERENCE_TOOL_ID,
        WEB_SEARCH_TOOL_ID,
        WEB_IMAGE_SEARCH_TOOL_ID,
        WEB_IMAGE_INSPECT_TOOL_ID,
        VISIT_WEBPAGE_TOOL_ID,
    }
)

# Deliberately withheld from the unattended loop, with the reason. A test requires every
# Course Agent tool to appear in exactly one of these two sets, so a new tool cannot reach
# the loop, or be forgotten, without a decision.
LOOP_WITHHELD_TOOL_IDS: dict[str, str] = {
    # The loop proposes; it never acts on people or publishes.
    INSTRUCTOR_MESSAGE_STUDENTS_TOOL_ID: "sends messages",
    ASK_TA_TOOL_ID: "sends a question to staff",
    SUBMIT_APPLICATION_TOOL_ID: "submits a record",
    SELECT_SHOWCASE_TOOL_ID: "publishes a selection",
    # Individual private records, whose content would enter stored phase conversations.
    GET_MY_GRADES_TOOL_ID: "individual grades",
    INSTRUCTOR_LIST_STUDENTS_TOOL_ID: "roster",
    INSTRUCTOR_LIST_APPLICATIONS_TOOL_ID: "applicant records",
    INSTRUCTOR_READ_APPLICATION_TOOL_ID: "applicant records",
    INSTRUCTOR_INSPECT_APPLICATION_IMAGES_TOOL_ID: "applicant records",
    LIST_FAQ_UPDATES_TOOL_ID: "student questions sent to staff",
    READ_FAQ_UPDATE_TOOL_ID: "student questions sent to staff",
    LIST_MY_COMMUNICATIONS_TOOL_ID: "a user's own messages",
    READ_MY_COMMUNICATION_TOOL_ID: "a user's own messages",
    INSPECT_MY_STUDENT_SITE_TOOL_ID: "a student's own project",
    INSPECT_MY_STUDENT_REPOSITORY_TOOL_ID: "a student's own project",
    READ_UPLOAD_TOOL_ID: "a user's upload",
    # Interactive surfaces with no viewer in a background run.
    DOCUMENT_INSPECT_PAGE_TOOL_ID: "interactive workspace",
    workspace_tools.LIST_COMPONENTS_TOOL_ID: "interactive workspace",
    workspace_tools.OPEN_COMPONENT_TOOL_ID: "interactive workspace",
    workspace_tools.UPDATE_COMPONENT_TOOL_ID: "interactive workspace",
    workspace_tools.FOCUS_COMPONENT_TOOL_ID: "interactive workspace",
    workspace_tools.CLOSE_COMPONENT_TOOL_ID: "interactive workspace",
    workspace_tools.REVIEW_PRESENTATION_TOOL_ID: "interactive workspace",
    browser_tools.BROWSER_OPEN_TOOL_ID: "interactive browser panel",
    browser_tools.BROWSER_COMPARE_TOOL_ID: "interactive browser panel",
    browser_tools.BROWSER_NAVIGATE_TOOL_ID: "interactive browser panel",
    browser_tools.BROWSER_SCROLL_TOOL_ID: "interactive browser panel",
    browser_tools.BROWSER_HIGHLIGHT_TEXT_TOOL_ID: "interactive browser panel",
}
