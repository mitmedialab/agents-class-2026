/**
 * Shared mock fixtures for Playwright E2E tests.
 * Data mirrors the unit-test fixtures in App.test.tsx to keep parity.
 */

export const PUBLIC_PRINCIPAL = {
  authenticated: false,
  user_id: null,
  anonymous_session_id: "10000000-0000-4000-8000-000000000001",
  username: null,
  display_name: null,
  roles: ["public"],
  session_id: "10000000-0000-4000-8000-000000000002",
};

export const STUDENT_PRINCIPAL = {
  authenticated: true,
  user_id: "10000000-0000-4000-8000-000000000003",
  anonymous_session_id: null,
  username: "alice",
  display_name: "Alice Example",
  roles: ["public", "student"],
  session_id: "10000000-0000-4000-8000-000000000004",
};

export const CONVERSATION = {
  id: "20000000-0000-4000-8000-000000000001",
  user_id: null,
  anonymous_session_id: PUBLIC_PRINCIPAL.anonymous_session_id,
  created_at: "2026-08-23T10:00:00Z",
  updated_at: "2026-08-23T10:05:00Z",
  title: "Week one",
  archived_at: null,
};

export const AGENT_MESSAGE_EVENT = {
  id: "30000000-0000-4000-8000-000000000001",
  schema_version: 1,
  timestamp: "2026-08-23T10:05:00Z",
  type: "agent.message",
  actor: "course-agent",
  principal_user_id: null,
  anonymous_session_id: PUBLIC_PRINCIPAL.anonymous_session_id,
  conversation_id: CONVERSATION.id,
  node_id: null,
  payload: { text: "The earlier response." },
  metadata: {},
};

export const SYLLABUS_MARKDOWN = [
  "# **AI Agents for Cognitive Augmentation**",
  "",
  "**Proposed instructors:** Valdemar Danry and Professor Pattie Maes",
  "**Format:** Weekly 2-hour session",
  "",
  "## **Course Overview**",
  "",
  "A hands-on graduate-level course.",
  "",
  "## **Assignments and Evaluation**",
  "",
  "| Component | Weight |",
  "| --- | --- |",
  "| Weekly technical builds | 35% |",
].join("\n");

export const SCHEDULE_JSON = JSON.stringify({
  status: "provisional",
  events: [
    {
      id: "review",
      title: "Project review",
      start: "2026-10-08T11:00:00-04:00",
      type: "class",
    },
  ],
});

/** Build a minimal SSE response body for a text-only agent reply. */
export function textSseStream(text: string): string {
  return [
    "event: message",
    `data: ${JSON.stringify({ type: "agent.text.done", text })}`,
    "",
    "event: done",
    `data: {}`,
    "",
    "",
  ].join("\n");
}

/** Build an SSE response that opens a calendar workspace panel then sends text. */
export function calendarSseStream(text: string): string {
  const platformEvent = {
    type: "workspace.panel.opened",
    event: {
      payload: {
        command: {
          type: "open",
          panel: {
            id: "40000000-0000-4000-8000-000000000001",
            component_id: "calendar",
            title: "Course schedule",
            props: { view: "agenda", focus_date: "2026-10-08" },
            state: {},
          },
        },
      },
    },
  };
  return [
    "event: platform",
    `data: ${JSON.stringify(platformEvent)}`,
    "",
    "event: message",
    `data: ${JSON.stringify({ type: "agent.text.done", text })}`,
    "",
    "event: done",
    `data: {}`,
    "",
    "",
  ].join("\n");
}
