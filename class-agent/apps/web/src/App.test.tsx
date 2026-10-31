import type { Conversation, PrincipalContext } from "@class-agent/protocol";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.js";
import * as api from "./api.js";

vi.mock("./api.js", () => ({
  applyWorkspacePanelAction: vi.fn(),
  clickBrowserSession: vi.fn(),
  confirmInstructorMessage: vi.fn(),
  confirmTAQuestion: vi.fn(),
  continueAgentAfterEvent: vi.fn(),
  createConversation: vi.fn(),
  ensureApplicationDraft: vi.fn(),
  generatePageGreeting: vi.fn(),
  getCourseResourceContent: vi.fn(),
  getConversation: vi.fn(),
  getInstructorMessageEmailDelivery: vi.fn(),
  getNotificationCenter: vi.fn(),
  getPendingActionConversation: vi.fn(),
  getPrincipal: vi.fn(),
  listConversations: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  markNotificationCenterItemRead: vi.fn(),
  recordWorkspaceInteraction: vi.fn(),
  resizeBrowserSession: vi.fn(),
  scrollBrowserSession: vi.fn(),
  streamAgentRun: vi.fn(),
  uploadFile: vi.fn(),
}));

const publicPrincipal: PrincipalContext = {
  authenticated: false,
  user_id: null,
  anonymous_session_id: "10000000-0000-4000-8000-000000000001",
  username: null,
  display_name: null,
  roles: ["public"],
  session_id: "10000000-0000-4000-8000-000000000002",
};

const studentPrincipal: PrincipalContext = {
  authenticated: true,
  user_id: "10000000-0000-4000-8000-000000000003",
  anonymous_session_id: null,
  username: "alice",
  display_name: "Alice Example",
  roles: ["public", "student"],
  session_id: "10000000-0000-4000-8000-000000000004",
};

const instructorPrincipal: PrincipalContext = {
  authenticated: true,
  user_id: "10000000-0000-4000-8000-000000000005",
  anonymous_session_id: null,
  username: "instructor",
  display_name: "Course Instructor",
  roles: ["public", "instructor"],
  session_id: "10000000-0000-4000-8000-000000000006",
};

const conversation: Conversation = {
  id: "20000000-0000-4000-8000-000000000001",
  user_id: null,
  anonymous_session_id: publicPrincipal.anonymous_session_id,
  created_at: "2026-08-23T10:00:00Z",
  updated_at: "2026-08-23T10:05:00Z",
  title: "Week one",
  archived_at: null,
};

const previousEvent = {
  id: "30000000-0000-4000-8000-000000000001",
  schema_version: 1 as const,
  timestamp: "2026-08-23T10:05:00Z",
  type: "agent.message",
  actor: "course-agent",
  principal_user_id: null,
  anonymous_session_id: publicPrincipal.anonymous_session_id,
  conversation_id: conversation.id,
  node_id: null,
  payload: { text: "The earlier response." },
  metadata: {},
};

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/");
  vi.mocked(api.getPrincipal).mockResolvedValue(publicPrincipal);
  vi.mocked(api.listConversations).mockResolvedValue([conversation]);
  vi.mocked(api.getNotificationCenter).mockResolvedValue({
    generated_at: "2026-09-05T12:00:00Z",
    unread_count: 0,
    items: [],
  });
  vi.mocked(api.getPendingActionConversation).mockResolvedValue(null);
  vi.mocked(api.generatePageGreeting).mockResolvedValue({
    output_text: "Hello. You have no new notifications or upcoming deadlines. We could review the schedule.",
    event_ids: [],
  });
  vi.mocked(api.markNotificationCenterItemRead).mockResolvedValue();
  vi.mocked(api.continueAgentAfterEvent).mockResolvedValue({
    output_text: "Course staff now have that question. What else should we work on?",
    event_ids: [],
  });
  vi.mocked(api.getConversation).mockResolvedValue({
    conversation,
    events: [previousEvent],
  });
  vi.mocked(api.getInstructorMessageEmailDelivery).mockResolvedValue({
    message_id: "30000000-0000-4000-8000-000000000001",
    state: "sent",
    total_recipients: 1,
    sent_recipients: 1,
    remaining_recipients: 0,
    failed_recipients: 0,
    deferred_recipients: 0,
    total_attempts: 1,
  });
  vi.mocked(api.createConversation).mockResolvedValue(conversation);
  vi.mocked(api.applyWorkspacePanelAction).mockResolvedValue(previousEvent);
  vi.mocked(api.ensureApplicationDraft).mockResolvedValue({
    ...previousEvent,
    id: "30000000-0000-4000-8000-000000000009",
    type: "workspace.panel.opened",
    payload: {
      command: {
        type: "open",
        panel: {
          id: "40000000-0000-4000-8000-000000000009",
          component_id: "draft-document",
          title: "Course Application Draft",
          resource_uri: "course://application",
          props: {
            title: "Course Application Draft",
            fields: [{ id: "name", label: "Name", value: "", status: "missing" }],
          },
          state: { document_kind: "course-application" },
        },
      },
    },
  });
  vi.mocked(api.getCourseResourceContent).mockImplementation(async (uri) => {
    if (uri === "course://syllabus") {
      return {
        pdfDownloadUrl: "/api/v1/course/resources/asset?uri=course%3A%2F%2Fsyllabus&asset_id=pdf",
        uri,
        mediaType: "text/markdown",
        data: new TextEncoder().encode(
          "# **AI Agents for Cognitive Augmentation**\n\n" +
            "**Proposed instructors:** Valdemar Danry and Professor Pattie Maes\n" +
            "**Format:** Weekly 2-hour session\n\n" +
            "## **Course Overview**\n\nA hands-on graduate-level course.\n\n" +
            "## **Assignments and Evaluation**\n\n| Component | Weight |\n| --- | --- |\n| Weekly technical builds | 35% |",
        ),
      };
    }
    return {
      uri,
      mediaType: "application/json",
      data: new TextEncoder().encode(
        JSON.stringify({
          status: "provisional",
          events: [
            {
              id: "review",
              title: "Project review",
              start: "2026-10-08T11:00:00-04:00",
              type: "class",
            },
          ],
        }),
      ),
    };
  });
  vi.mocked(api.login).mockResolvedValue(studentPrincipal);
  vi.mocked(api.logout).mockResolvedValue();
  vi.mocked(api.recordWorkspaceInteraction).mockResolvedValue({
    ...previousEvent,
    id: "30000000-0000-4000-8000-000000000008",
    type: "workspace.interaction",
    actor: "user",
    payload: {
      panel_id: "40000000-0000-4000-8000-000000000001",
      component_id: "calendar",
      action: "calendar.select_event",
      value: "review",
    },
  });
  vi.mocked(api.streamAgentRun).mockResolvedValue();
  vi.mocked(api.uploadFile).mockResolvedValue({
    id: "40000000-0000-4000-8000-000000000001",
    filename: "portrait.png",
    media_type: "image/png",
    size_bytes: 12,
    created_at: "2026-08-23T10:00:00Z",
    expires_at: "2026-08-24T10:00:00Z",
  });
});

async function openExistingConversation(): Promise<void> {
  await waitFor(() => expect(api.listConversations).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: "Your logs" }));
  fireEvent.click(await screen.findByRole("button", { name: /Week one/ }));
  await screen.findByText("The earlier response.");
}

describe("Course Agent interface", () => {
  it("introduces the course before revealing the interface", async () => {
    vi.useFakeTimers();
    try {
      render(<App />);

      expect(screen.getByTestId("opening-splash")).toBeInTheDocument();
      expect(
        screen.getByRole("heading", {
          name: "MAS.S60 · AI Agents for Cognitive Augmentation",
        }),
      ).toBeInTheDocument();
      expect(screen.getByTestId("course-agent-interface")).toHaveAttribute(
        "inert",
      );

      act(() => vi.advanceTimersByTime(3_599));
      expect(screen.getByTestId("opening-splash")).toBeInTheDocument();

      await act(async () => {
        vi.advanceTimersByTime(1);
        await Promise.resolve();
      });
      expect(screen.queryByTestId("opening-splash")).not.toBeInTheDocument();
      expect(screen.getByTestId("course-agent-interface")).not.toHaveAttribute(
        "inert",
      );
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });

  it("starts fresh on page load while retaining previous conversations in history", async () => {
    render(<App />);

    await waitFor(() => expect(api.listConversations).toHaveBeenCalled());
    expect(document.querySelector(".latest-response")).toHaveTextContent(
      /Welcome\. I’m the Course Agent/,
    );
    expect(api.getConversation).not.toHaveBeenCalled();
    expect(api.createConversation).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "MIT" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "MIT Media Lab" })).toBeInTheDocument();
    const newChat = screen.getByRole("button", { name: "New chat" });
    expect(newChat).toBe(document.querySelector(".header-utility")?.firstElementChild);
    expect(newChat.querySelector("svg")).toBeNull();
    expect(
      screen.getByRole("navigation", { name: "Course shortcuts" }).previousElementSibling,
    ).toBe(newChat);
    expect(screen.getByRole("button", { name: "Your logs" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Schedule" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Grading" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "About" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect AI" })).toHaveAttribute(
      "href",
      "/ai-connect",
    );
    expect(screen.getByText("Course Agent")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveAttribute(
      "placeholder",
      "Start typing to interact with the agent",
    );
    const workspaceShell = screen.getByTestId("workspace-shell");
    const composerForm = screen.getByRole("form", { name: "Message Course Agent" });
    expect(workspaceShell).toContainElement(composerForm);
    fireEvent.click(screen.getByRole("button", { name: "Your logs" }));
    expect(screen.getByRole("button", { name: /Week one/ })).toBeInTheDocument();
  });

  it("scrolls backward through assistant moments and restores their workspace", async () => {
    vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
    vi.mocked(api.getNotificationCenter).mockResolvedValue({
      generated_at: "2026-09-05T12:00:00Z",
      unread_count: 1,
      items: [{
        id: "60000000-0000-4000-8000-000000000001",
        section: "notifications",
        kind: "course_update",
        state: "unread",
        title: "Project update",
        detail: "A new project note is available.",
        timestamp: "2026-09-05T12:00:00Z",
        due_at: null,
        action_label: "Discuss update",
        action_prompt: "Explain this update.",
        unread: true,
        dismissible: true,
        sender: null,
      }],
    });
    const workspaceOpened = {
      ...previousEvent,
      id: "30000000-0000-4000-8000-000000000010",
      timestamp: "2026-08-23T10:06:00Z",
      type: "workspace.panel.opened",
      payload: {
        command: {
          type: "open",
          panel: {
            id: "40000000-0000-4000-8000-000000000010",
            component_id: "calendar",
            title: "Course schedule",
            resource_uri: "course://schedule",
            props: {},
            state: {},
          },
        },
      },
    };
    const latestEvent = {
      ...previousEvent,
      id: "30000000-0000-4000-8000-000000000013",
      timestamp: "2026-08-23T10:09:00Z",
      payload: { text: "The current response." },
    };
    const workspaceResponse = {
      ...previousEvent,
      id: "30000000-0000-4000-8000-000000000011",
      timestamp: "2026-08-23T10:07:00Z",
      payload: { text: "The schedule is open." },
    };
    const workspacePrompt = {
      ...previousEvent,
      id: "30000000-0000-4000-8000-000000000014",
      timestamp: "2026-08-23T10:05:30Z",
      type: "user.message",
      actor: "user",
      payload: { text: "Show me the course schedule." },
    };
    const closePrompt = {
      ...previousEvent,
      id: "30000000-0000-4000-8000-000000000015",
      timestamp: "2026-08-23T10:07:30Z",
      type: "user.message",
      actor: "user",
      payload: { text: "Close the schedule and summarize it." },
    };
    const workspaceClosed = {
      ...previousEvent,
      id: "30000000-0000-4000-8000-000000000012",
      timestamp: "2026-08-23T10:08:00Z",
      type: "workspace.panel.closed",
      payload: {
        command: {
          type: "close",
          panel_id: "40000000-0000-4000-8000-000000000010",
        },
      },
    };
    vi.mocked(api.getConversation).mockResolvedValue({
      conversation,
      events: [
        previousEvent,
        workspacePrompt,
        workspaceOpened,
        workspaceResponse,
        closePrompt,
        workspaceClosed,
        latestEvent,
      ],
    });

    render(<App />);
    await waitFor(() => expect(api.listConversations).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Your logs" }));
    fireEvent.click(await screen.findByRole("button", { name: /Week one/ }));

    expect(await screen.findByText("The current response.")).toBeInTheDocument();
    expect(within(document.querySelector(".timeline-message-group")!).getByText("Close the schedule and summarize it.")).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Workspace" })).not.toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Notification center" })).toBeInTheDocument();

    const stage = document.querySelector(".response-stage")!;
    Object.defineProperty(stage, "scrollHeight", { configurable: true, value: 600 });
    Object.defineProperty(stage, "clientHeight", { configurable: true, value: 300 });
    Object.defineProperty(stage, "scrollTop", { configurable: true, writable: true, value: 80 });
    const ordinaryScroll = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: -80 });
    stage.dispatchEvent(ordinaryScroll);
    expect(ordinaryScroll.defaultPrevented).toBe(false);
    expect(document.querySelector(".timeline-preview-message-group")).not.toBeInTheDocument();
    stage.scrollTop = 0;

    const timelineScroll = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: -160 });
    act(() => { stage.dispatchEvent(timelineScroll); });
    expect(timelineScroll.defaultPrevented).toBe(true);
    expect(document.querySelector(".timeline-preview-message-group")).toHaveTextContent("Show me the course schedule.");
    expect(document.querySelector(".timeline-workspace-preview")).toHaveAttribute("aria-hidden", "true");
    expect(document.querySelector(".conversation-timeline")).toHaveAttribute("data-scrubbing", "true");
    expect(document.querySelector(".course-agent")).toHaveAttribute("data-timeline-transition", "true");
    expect(document.querySelector(".timeline-message-group .latest-response")).toHaveAttribute("data-response-fit", "fixed");
    expect(document.querySelector(".timeline-preview-message-group .latest-response")).toHaveAttribute("data-response-fit", "fixed");
    const agent = document.querySelector<HTMLElement>(".course-agent")!;
    expect(agent.style.getPropertyValue("--timeline-outgoing-opacity")).toBe("0");
    expect(agent.style.getPropertyValue("--timeline-incoming-opacity")).toBe("0");
    expect(agent.style.getPropertyValue("--timeline-header-opacity")).toBe("0");
    expect(agent.style.getPropertyValue("--timeline-notification-opacity")).toBe("0");
    fireEvent.wheel(stage, { deltaY: -40 });
    expect(agent).toHaveAttribute("data-timeline-target-flow", "true");
    expect(agent.style.getPropertyValue("--timeline-outgoing-opacity")).toBe("0");
    expect(agent.style.getPropertyValue("--timeline-incoming-opacity")).toBe("0");
    fireEvent.wheel(stage, { deltaY: 120 });
    expect(within(document.querySelector(".timeline-message-group")!).getByText("The current response.")).toBeInTheDocument();
    await waitFor(() =>
      expect(document.querySelector(".conversation-timeline")).toHaveAttribute("data-active", "false"),
    );
    fireEvent.wheel(stage, { deltaY: -120 });
    fireEvent.wheel(stage, { deltaY: -120 });
    expect(document.querySelector(".timeline-preview-message-group")).toHaveTextContent("The schedule is open.");

    await waitFor(() =>
      expect(within(document.querySelector(".timeline-message-group:not(.timeline-preview-message-group)")!).getByText("The schedule is open.")).toBeInTheDocument(),
    );
    expect(within(document.querySelector(".timeline-message-group")!).getByText("Show me the course schedule.")).toBeInTheDocument();
    expect(screen.queryByText("Close the schedule and summarize it.")).not.toBeInTheDocument();
    const historicalWorkspace = screen.getByRole("complementary", {
      name: "Workspace",
    });
    expect(historicalWorkspace).toHaveAttribute("data-history", "true");
    expect(screen.queryByRole("complementary", { name: "Notification center" })).not.toBeInTheDocument();
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute("data-notifications-open", "false");
    expect(historicalWorkspace.querySelector("[inert]")).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Month" }));
    expect(screen.getByRole("button", { name: "Month" })).toHaveAttribute("aria-pressed", "true");
    expect(api.recordWorkspaceInteraction).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeDisabled();
    expect(document.querySelector(".timeline-pager")).toHaveAttribute("aria-description", "Moment 2 of 3");

    fireEvent.click(screen.getByRole("button", { name: "Go to an older assistant response" }));
    expect(screen.getByRole("complementary", { name: "Notification center" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Workspace" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Go to a newer assistant response" }));
    expect(screen.queryByRole("complementary", { name: "Notification center" })).not.toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Workspace" })).toHaveAttribute("data-history", "true");

    stage.scrollTop = 300;
    fireEvent.wheel(stage, { deltaY: 100 });
    expect(document.querySelector(".timeline-preview-message-group")).toHaveTextContent("The current response.");
    fireEvent.wheel(stage, { deltaY: -60 });
    await waitFor(() =>
      expect(document.querySelector(".timeline-preview-message-group")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("complementary", { name: "Workspace" })).toHaveAttribute("data-history", "true");

    fireEvent.click(screen.getByRole("button", { name: "Return to current response" }));

    expect(await screen.findByText("The current response.")).toBeInTheDocument();
    expect(within(document.querySelector(".timeline-message-group")!).getByText("Close the schedule and summarize it.")).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Workspace" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Schedule" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Discuss update: Project update" })).toBeEnabled();

    fireEvent.touchStart(stage, { touches: [{ clientY: 200 }] });
    fireEvent.touchMove(stage, { touches: [{ clientY: 440 }] });
    expect(document.querySelector(".conversation-timeline")).toHaveAttribute("data-scrubbing", "true");
    expect(within(document.querySelector(".timeline-message-group")!).getByText("The current response.")).toBeInTheDocument();
    fireEvent.touchEnd(stage, { changedTouches: [{ clientY: 440 }] });
    await waitFor(() =>
      expect(within(document.querySelector(".timeline-message-group:not(.timeline-preview-message-group)")!).getByText("Show me the course schedule.")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Go to an older assistant response" }));
    expect(screen.getByRole("button", { name: "Schedule" })).toBeEnabled();
    expect(screen.getByRole("complementary", { name: "Notification center" })).not.toHaveAttribute("inert");
    fireEvent.click(screen.getByRole("button", { name: "Schedule" }));
    await waitFor(() =>
      expect(api.streamAgentRun).toHaveBeenCalledWith(
        conversation.id,
        "Show me the course schedule.",
        expect.any(Function),
        expect.any(AbortSignal),
      ),
    );
    expect(document.querySelector(".course-agent")).toHaveAttribute("data-time-traveling", "false");
  });

  it("reveals notifications in an older chat moment even when the current workspace hides them", async () => {
    vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
    vi.mocked(api.getNotificationCenter).mockResolvedValue({
      generated_at: "2026-09-05T12:00:00Z",
      unread_count: 1,
      items: [{
        id: "60000000-0000-4000-8000-000000000001",
        section: "notifications",
        kind: "course_update",
        state: "unread",
        title: "Project update",
        detail: "A new project note is available.",
        timestamp: "2026-09-05T12:00:00Z",
        due_at: null,
        action_label: "Discuss update",
        action_prompt: "Explain this update.",
        unread: true,
        dismissible: true,
        sender: null,
      }],
    });
    vi.mocked(api.getConversation).mockResolvedValue({
      conversation,
      events: [
        previousEvent,
        {
          ...previousEvent,
          id: "30000000-0000-4000-8000-000000000010",
          type: "workspace.panel.opened",
          payload: {
            command: {
              type: "open",
              panel: {
                id: "40000000-0000-4000-8000-000000000010",
                component_id: "calendar",
                title: "Course schedule",
                resource_uri: "course://schedule",
                props: {},
                state: {},
              },
            },
          },
        },
        {
          ...previousEvent,
          id: "30000000-0000-4000-8000-000000000011",
          payload: { text: "The schedule is open." },
        },
      ],
    });

    render(<App />);
    await waitFor(() => expect(api.listConversations).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Your logs" }));
    fireEvent.click(await screen.findByRole("button", { name: /Week one/ }));
    expect(await screen.findByText("The schedule is open.")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Notification center" })).not.toBeInTheDocument();

    const stage = document.querySelector(".response-stage")!;
    Object.defineProperty(stage, "scrollHeight", { configurable: true, value: 300 });
    Object.defineProperty(stage, "clientHeight", { configurable: true, value: 300 });
    fireEvent.wheel(stage, { deltaY: -220 });
    expect(screen.getByRole("complementary", { name: "Notification center" })).toBeInTheDocument();
    expect(Number(document.querySelector<HTMLElement>(".course-agent")!.style.getPropertyValue("--timeline-notification-opacity"))).toBeGreaterThan(0);

    await waitFor(() =>
      expect(within(document.querySelector(".timeline-message-group:not(.timeline-preview-message-group)")!).getByText("The earlier response.")).toBeInTheDocument(),
    );
    expect(screen.getByRole("complementary", { name: "Notification center" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Workspace" })).not.toBeInTheDocument();

    const historicalUpdate = screen.getByRole("button", { name: "Discuss update: Project update" });
    expect(historicalUpdate).toBeEnabled();
    expect(screen.getByRole("complementary", { name: "Notification center" })).not.toHaveAttribute("inert");
    fireEvent.click(historicalUpdate);
    await waitFor(() =>
      expect(api.streamAgentRun).toHaveBeenCalledWith(
        conversation.id,
        "Explain this update.",
        expect.any(Function),
        expect.any(AbortSignal),
      ),
    );
    expect(document.querySelector(".course-agent")).toHaveAttribute("data-time-traveling", "false");
    expect(screen.getByRole("complementary", { name: "Workspace" })).toBeInTheDocument();

    expect(screen.queryByRole("complementary", { name: "Notification center" })).not.toBeInTheDocument();
  });

  it("requires a new wheel gesture before moving past the adjacent moment", async () => {
    vi.mocked(api.getConversation).mockResolvedValue({
      conversation,
      events: [
        previousEvent,
        {
          ...previousEvent,
          id: "30000000-0000-4000-8000-000000000021",
          payload: { text: "The middle response." },
        },
        {
          ...previousEvent,
          id: "30000000-0000-4000-8000-000000000022",
          payload: { text: "The latest response." },
        },
      ],
    });

    render(<App />);
    await waitFor(() => expect(api.listConversations).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Your logs" }));
    fireEvent.click(await screen.findByRole("button", { name: /Week one/ }));
    expect(await screen.findByText("The latest response.")).toBeInTheDocument();

    const stage = document.querySelector(".response-stage")!;
    Object.defineProperty(stage, "scrollHeight", { configurable: true, value: 300 });
    Object.defineProperty(stage, "clientHeight", { configurable: true, value: 300 });
    fireEvent.wheel(stage, { deltaY: -80 });
    expect(document.querySelector(".timeline-pager")).toHaveAttribute("aria-description", "Moment 3 of 3");
    await waitFor(() =>
      expect(document.querySelector(".timeline-preview-message-group")).not.toBeInTheDocument(),
    );

    fireEvent.wheel(stage, { deltaY: -600 });
    await waitFor(() =>
      expect(within(document.querySelector(".timeline-message-group:not(.timeline-preview-message-group)")!).getByText("The middle response.")).toBeInTheDocument(),
    );
    const continuedScroll = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: -600 });
    act(() => { stage.dispatchEvent(continuedScroll); });
    expect(continuedScroll.defaultPrevented).toBe(true);
    expect(document.querySelector(".timeline-pager")).toHaveAttribute("aria-description", "Moment 2 of 3");
    expect(document.querySelector(".timeline-preview-message-group")).not.toBeInTheDocument();

    await new Promise((resolve) => window.setTimeout(resolve, 480));
    fireEvent.wheel(stage, { deltaY: -600 });
    await waitFor(() =>
      expect(within(document.querySelector(".timeline-message-group:not(.timeline-preview-message-group)")!).getByText("The earlier response.")).toBeInTheDocument(),
    );
  });

  it("starts a fresh conversation from a shared q query and consumes the parameter", async () => {
    vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
    const sharedConversation = {
      ...conversation,
      user_id: studentPrincipal.user_id,
      anonymous_session_id: null,
      title: "How does grading work?",
    };
    vi.mocked(api.createConversation).mockResolvedValue(sharedConversation);
    window.history.replaceState(
      { source: "shared-link" },
      "",
      "/?q=%20How%20does%20grading%20work%3F%20&ref=course#overview",
    );

    render(<App />);

    await waitFor(() =>
      expect(api.streamAgentRun).toHaveBeenCalledWith(
        sharedConversation.id,
        "How does grading work?",
        expect.any(Function),
        expect.any(AbortSignal),
      ),
    );
    expect(api.createConversation).toHaveBeenCalledWith("How does grading work?");
    expect(api.generatePageGreeting).not.toHaveBeenCalled();
    expect(api.getPendingActionConversation).not.toHaveBeenCalled();
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      "/?ref=course#overview",
    );
    expect(window.history.state).toEqual({ source: "shared-link" });
  });

  it("does not submit a blank shared q query", async () => {
    window.history.replaceState({}, "", "/?q=%20%20");

    render(<App />);

    await waitFor(() => expect(api.listConversations).toHaveBeenCalled());
    expect(document.querySelector(".latest-response")).toHaveTextContent(
      /Welcome\. I’m the Course Agent/,
    );
    expect(api.streamAgentRun).not.toHaveBeenCalled();
    expect(window.location.search).toBe("");
  });

  it("rejects an oversized shared q query without truncating or submitting it", async () => {
    const query = new URLSearchParams({ q: "x".repeat(20_001) });
    window.history.replaceState({}, "", `/?${query.toString()}`);

    render(<App />);

    expect(
      await screen.findByText(
        "This shared query is too long. Shorten it to 20,000 characters or fewer and try again.",
      ),
    ).toBeVisible();
    expect(api.createConversation).not.toHaveBeenCalled();
    expect(api.streamAgentRun).not.toHaveBeenCalled();
    expect(window.location.search).toBe("");
  });

  it("loads conversation history five at a time", async () => {
    const history = Array.from({ length: 12 }, (_, index) => ({
      ...conversation,
      id: `20000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      title: `Conversation ${index + 1}`,
      updated_at: new Date(Date.parse(conversation.updated_at) - index * 60_000).toISOString(),
    }));
    vi.mocked(api.listConversations).mockImplementation(
      async ({ limit, offset = 0 } = {}) => history.slice(offset, offset + (limit ?? 0)),
    );

    render(<App />);
    await waitFor(() => expect(api.listConversations).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Your logs" }));

    expect(screen.getAllByRole("button", { name: /Conversation \d/ })).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "Show 5 more" }));

    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /Conversation \d/ })).toHaveLength(10),
    );
    expect(api.listConversations).toHaveBeenLastCalledWith({ limit: 6, offset: 5 });
    expect(screen.getByRole("button", { name: "Show 5 more" })).toBeInTheDocument();
  });

  it("keeps an expanding multiline composer in the workspace layout flow", () => {
    render(<App />);

    const composer = screen.getByRole<HTMLTextAreaElement>("textbox", {
      name: "Message",
    });
    Object.defineProperty(composer, "scrollHeight", {
      configurable: true,
      value: 240,
    });

    fireEvent.change(composer, {
      target: { value: "A long draft\nwith enough lines\nto expand the composer" },
    });

    expect(composer).toHaveStyle({ height: "160px" });
    expect(
      screen.getByRole("form", { name: "Message Course Agent" }).parentElement,
    ).toBe(screen.getByTestId("workspace-shell"));
  });

  it("requires the student to confirm question details without exposing email metadata", async () => {
    const studentConversation = {
      ...conversation,
      user_id: studentPrincipal.user_id,
      anonymous_session_id: null,
    };
    vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
    vi.mocked(api.listConversations).mockResolvedValue([]);
    vi.mocked(api.createConversation).mockResolvedValue(studentConversation);
    vi.mocked(api.streamAgentRun).mockImplementation(
      async (_conversationId, _text, onEvent) => {
        onEvent({
          kind: "ta_question_confirmation",
          confirmation: {
            id: "50000000-0000-4000-8000-000000000001",
            code: "Q-2026-00001",
            subject: "Assignment model",
            question: "May I use a local model?",
            context: "The assignment page does not specify deployment.",
            status: "pending_confirmation",
          },
        });
        onEvent({
          kind: "text_final",
          text: (
            "The course materials do not answer this, so I can ask the teaching " +
            "team for a definitive answer."
          ),
        });
        onEvent({ kind: "done" });
      },
    );
    vi.mocked(api.confirmTAQuestion).mockResolvedValue({
      ...previousEvent,
      type: "email.ta_question.queued",
      principal_user_id: studentPrincipal.user_id,
      anonymous_session_id: null,
      conversation_id: studentConversation.id,
      payload: {
        question_id: "50000000-0000-4000-8000-000000000001",
        question_code: "Q-2026-00001",
        status: "queued",
      },
    });

    render(<App />);
    await waitFor(() => expect(api.listConversations).toHaveBeenCalled());
    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "Ask course staff" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    expect(
      await screen.findByRole("region", {
        name: "Course staff question confirmation",
      }),
    ).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "Ask course staff?" }),
    ).not.toBeInTheDocument();
    expect(document.querySelector(".latest-response")).toHaveTextContent(
      "The course materials do not answer this, so I can ask the teaching team for a definitive answer.",
    );
    expect(
      screen.queryByText("I can ask course staff about this."),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Question" })).toHaveValue(
      "May I use a local model?",
    );
    expect(
      screen.queryByText("The assignment page does not specify deployment."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Q-2026-00001")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Subject" })).not.toBeInTheDocument();
    expect(composer).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "Question" }), {
      target: { value: "May I use a local open-weight model?" },
    });
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Hide my name from course staff" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(api.confirmTAQuestion).toHaveBeenCalledWith(
        studentConversation.id,
        "50000000-0000-4000-8000-000000000001",
        "send",
        "anonymous",
        {
          question: "May I use a local open-weight model?",
        },
      ),
    );
    await waitFor(() =>
      expect(api.continueAgentAfterEvent).toHaveBeenCalledWith(
        studentConversation.id,
        previousEvent.id,
      ),
    );
    expect(
      await screen.findByText(
        "Course staff now have that question. What else should we work on?",
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("region", {
        name: "Course staff question confirmation",
      }),
    ).not.toBeInTheDocument();
    expect(composer).toBeEnabled();
    fireEvent.change(composer, { target: { value: "I have another question" } });
    expect(composer).toHaveValue("I have another question");
  });

  it("restores the agent-generated continuation without reopening the confirmation", async () => {
    const studentConversation = {
      ...conversation,
      user_id: studentPrincipal.user_id,
      anonymous_session_id: null,
    };
    const questionId = "50000000-0000-4000-8000-000000000001";
    vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
    vi.mocked(api.listConversations).mockResolvedValue([studentConversation]);
    vi.mocked(api.getConversation).mockResolvedValue({
      conversation: studentConversation,
      events: [
        previousEvent,
        {
          ...previousEvent,
          id: "50000000-0000-4000-8000-000000000002",
          type: "email.ta_question.confirmation_requested",
          payload: {
            question_id: questionId,
            question_code: "Q-2026-00001",
            subject: "Assignment model",
            question: "May I use a local model?",
          },
        },
        {
          ...previousEvent,
          id: "50000000-0000-4000-8000-000000000003",
          type: "email.ta_question.queued",
          payload: { question_id: questionId, status: "queued" },
        },
        {
          ...previousEvent,
          id: "50000000-0000-4000-8000-000000000004",
          type: "agent.message",
          payload: {
            text: "The question is with course staff. Let's continue with your other topic.",
            input_id: "50000000-0000-4000-8000-000000000005",
          },
          metadata: {
            trigger_event_id: "50000000-0000-4000-8000-000000000003",
          },
        },
      ],
    });

    render(<App />);
    await waitFor(() => expect(api.listConversations).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Your logs" }));
    fireEvent.click(screen.getByRole("button", { name: /Week one/ }));

    expect(
      await screen.findByText(
        "The question is with course staff. Let's continue with your other topic.",
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("region", {
        name: "Course staff question confirmation",
      }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeEnabled();
  });

  it("restores a pending question reply with visibility choices and agent revisions", async () => {
    const instructorConversation = {
      ...conversation,
      user_id: instructorPrincipal.user_id,
      anonymous_session_id: null,
    };
    const messageId = "50000000-0000-4000-8000-000000000006";
    const confirmationEvent = {
      ...previousEvent,
      id: "50000000-0000-4000-8000-000000000007",
      type: "instructor.message.confirmation_requested",
      principal_user_id: instructorPrincipal.user_id,
      anonymous_session_id: null,
      conversation_id: instructorConversation.id,
      payload: {
        message_id: messageId,
        audience: "specific_students",
        recipients: [{ username: "alice", display_name: "Alice Example" }],
        recipient_count: 1,
        subject: "Studio reminder",
        message: "Bring your prototype.",
        source_question_id: "4e1b74b6-b3cd-4012-b96a-6c57c634b3e1",
        publication_decision: "private",
        status: "pending_confirmation",
      },
    };
    vi.mocked(api.getPrincipal).mockResolvedValue(instructorPrincipal);
    vi.mocked(api.listConversations).mockResolvedValue([instructorConversation]);
    const pendingDetail = {
      conversation: instructorConversation,
      events: [
        {
          ...previousEvent,
          principal_user_id: instructorPrincipal.user_id,
          anonymous_session_id: null,
          conversation_id: instructorConversation.id,
          payload: { text: "Please review this message before sending it." },
        },
        confirmationEvent,
      ],
    };
    const cancelledEvent = {
      ...confirmationEvent,
      id: "50000000-0000-4000-8000-000000000008",
      type: "instructor.message.cancelled",
      payload: { message_id: messageId, status: "cancelled" },
    };
    vi.mocked(api.getConversation).mockResolvedValue({
      conversation: instructorConversation,
      events: [...pendingDetail.events, cancelledEvent],
    });
    vi.mocked(api.getPendingActionConversation).mockResolvedValue(pendingDetail);
    vi.mocked(api.confirmInstructorMessage).mockResolvedValue(cancelledEvent);

    render(<App />);

    const confirmation = await screen.findByRole("region", {
      name: "Student message confirmation",
    });
    expect(confirmation).toBeVisible();
    expect(
      within(confirmation).getByRole("textbox", { name: "Subject" }),
    ).toHaveValue("Studio reminder");
    expect(within(confirmation).getByRole("radio", { name: "Private" })).toBeChecked();
    expect(within(confirmation).getByRole("radio", { name: "Public" })).toBeEnabled();
    expect(
      within(confirmation).getByRole("radio", { name: "Silently push to FAQ" }),
    ).toBeEnabled();
    expect(
      within(screen.getByRole("form", { name: "Message Course Agent" })).getByRole(
        "textbox",
        { name: "Message" },
      ),
    ).toBeEnabled();
    expect(api.createConversation).not.toHaveBeenCalled();
    expect(api.generatePageGreeting).not.toHaveBeenCalled();

    const composerForm = screen.getByRole("form", {
      name: "Message Course Agent",
    });
    expect(
      within(composerForm).queryByRole("button", { name: "Discard draft" }),
    ).not.toBeInTheDocument();
    const send = within(confirmation).getByRole("button", { name: "Send" });
    const cancel = within(confirmation).getByRole("button", { name: "Cancel" });
    expect(send.parentElement).toBe(cancel.parentElement);
    const composer = within(composerForm).getByRole("textbox", { name: "Message" });
    expect(composer).toHaveAttribute("placeholder", "Ask the agent to revise this draft");
    fireEvent.change(composer, {
      target: { value: "Make the message warmer and keep the same recipients." },
    });
    fireEvent.submit(composerForm);

    await waitFor(() =>
      expect(api.confirmInstructorMessage).toHaveBeenCalledWith(
        instructorConversation.id,
        messageId,
        "cancel",
        undefined,
      ),
    );
    await waitFor(() =>
      expect(api.streamAgentRun).toHaveBeenCalledWith(
        instructorConversation.id,
        "Make the message warmer and keep the same recipients.",
        expect.any(Function),
        expect.any(AbortSignal),
      ),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("region", { name: "Student message confirmation" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("shows student notifications automatically and removes the surface when caught up", async () => {
    vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
    vi.mocked(api.listConversations).mockResolvedValue([]);
    vi.mocked(api.getNotificationCenter).mockResolvedValue({
      generated_at: "2026-09-05T12:00:00Z",
      unread_count: 1,
      items: [
        {
          id: "60000000-0000-4000-8000-000000000001",
          section: "notifications",
          kind: "course_update",
          state: "unread",
          title: "Which assignments use groups?",
          detail: "Assignments 2 and 4 use groups.",
          timestamp: "2026-09-05T12:00:00Z",
          due_at: null,
          action_label: "Discuss update",
          action_prompt: "Explain this update.",
          unread: true,
          dismissible: true,
          sender: null,
        },
      ],
    });
    vi.mocked(api.generatePageGreeting).mockResolvedValue({
      output_text:
        "Hello Alice. There is a new course clarification; we can review it together.",
      event_ids: [],
    });

    render(<App />);

    expect(
      await screen.findByRole("complementary", { name: "Notification center" }),
    ).toBeVisible();
    const mobileView = screen.getByRole("group", { name: "Mobile view" });
    const chatView = within(mobileView).getByRole("button", { name: "Chat" });
    const updatesView = within(mobileView).getByRole("button", {
      name: /Notifications/,
    });
    expect(chatView).toHaveAttribute("aria-pressed", "true");
    expect(updatesView).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(updatesView);
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-mobile-notifications-open",
      "true",
    );
    fireEvent.click(chatView);
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-mobile-notifications-open",
      "false",
    );
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-notifications-open",
      "true",
    );
    expect(screen.getByText("Which assignments use groups?")).toBeVisible();
    expect(
      await screen.findByText(
        "Hello Alice. There is a new course clarification; we can review it together.",
      ),
    ).toBeVisible();
    expect(api.createConversation).toHaveBeenCalledWith("Course Agent welcome");
    expect(api.generatePageGreeting).toHaveBeenCalledWith(
      conversation.id,
      expect.any(AbortSignal),
    );
    fireEvent.click(screen.getByRole("button", { name: "Schedule" }));
    await waitFor(() =>
      expect(api.streamAgentRun).toHaveBeenCalledWith(
        conversation.id,
        "Show me the course schedule.",
        expect.any(Function),
        expect.any(AbortSignal),
      ),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Mark “Which assignments use groups?” read",
      }),
    );

    await waitFor(() =>
      expect(api.markNotificationCenterItemRead).toHaveBeenCalledWith(
        "60000000-0000-4000-8000-000000000001",
      ),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("complementary", { name: "Notification center" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-notifications-open",
      "false",
    );
  });

  it("polls for new notifications after one minute without removing the current snapshot", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
      vi.mocked(api.listConversations).mockResolvedValue([]);
      vi.mocked(api.getNotificationCenter)
        .mockResolvedValueOnce({
          generated_at: "2026-09-16T06:00:00Z",
          unread_count: 1,
          items: [
            {
              id: "60000000-0000-4000-8000-000000000041",
              section: "notifications",
              kind: "course_update",
              state: "unread",
              title: "Earlier update",
              detail: "Keep this update until the page refreshes.",
              timestamp: "2026-09-16T06:00:00Z",
              due_at: null,
              action_label: "Discuss update",
              action_prompt: "Discuss the earlier update.",
              unread: true,
              dismissible: true,
              sender: null,
            },
          ],
        })
        .mockResolvedValueOnce({
          generated_at: "2026-09-16T06:01:00Z",
          unread_count: 1,
          items: [
            {
              id: "60000000-0000-4000-8000-000000000042",
              section: "notifications",
              kind: "course_update",
              state: "unread",
              title: "New update",
              detail: "This update arrived while the page was open.",
              timestamp: "2026-09-16T06:01:00Z",
              due_at: null,
              action_label: "Discuss update",
              action_prompt: "Discuss the new update.",
              unread: true,
              dismissible: true,
              sender: null,
            },
          ],
        });

      render(<App />);
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(api.getNotificationCenter).toHaveBeenCalledTimes(1);

      await act(async () => {
        vi.advanceTimersByTime(60_000);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(api.getNotificationCenter).toHaveBeenCalledTimes(2);
      expect(screen.getByText("Earlier update")).toBeVisible();
      expect(screen.getByText("New update")).toBeVisible();
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });

  it("starts the bounded submission check from an assignment notification", async () => {
    const submissionPrompt =
      "Rigorously check my assignment. Follow the assignment-submission-check skill.";
    vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
    vi.mocked(api.listConversations).mockResolvedValue([]);
    vi.mocked(api.getNotificationCenter).mockResolvedValue({
      generated_at: "2026-09-05T12:00:00Z",
      unread_count: 0,
      items: [
        {
          id: "60000000-0000-4000-8000-000000000041",
          section: "upcoming",
          kind: "assignment_deadline",
          state: "upcoming",
          title: "Assignment one",
          detail: "Build and deploy the assignment.",
          timestamp: null,
          due_at: "2026-09-17T12:00:00Z",
          action_label: "View details",
          action_prompt: "Open assignment one.",
          submission_check_prompt: submissionPrompt,
          unread: false,
          dismissible: false,
          sender: null,
        },
      ],
    });

    render(<App />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Review my progress: Assignment one",
      }),
    );

    await waitFor(() =>
      expect(api.streamAgentRun).toHaveBeenCalledWith(
        conversation.id,
        submissionPrompt,
        expect.any(Function),
        expect.any(AbortSignal),
      ),
    );
  });

  it("opens a communication without running the agent and waits for an explicit query", async () => {
    const actionPrompt =
      "Show me any additional information available about the instructor message titled “Studio reminder”. Do not solve it or recommend an action. Ask what I want to do next.";
    const agentResponse = "What would you like to do with this message?";
    vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
    vi.mocked(api.listConversations).mockResolvedValue([]);
    vi.mocked(api.getNotificationCenter).mockResolvedValue({
      generated_at: "2026-09-05T12:00:00Z",
      unread_count: 0,
      items: [],
      history_items: [
        {
          id: "60000000-0000-4000-8000-000000000031",
          section: "communications",
          kind: "instructor_message",
          state: "read",
          title: "Studio reminder",
          detail: "Bring your prototype to class.",
          timestamp: "2026-09-04T12:00:00Z",
          due_at: null,
          action_label: "View details",
          action_prompt: actionPrompt,
          unread: false,
          dismissible: false,
          sender: null,
        },
      ],
    });
    vi.mocked(api.streamAgentRun).mockImplementation(async (_id, _text, onEvent) => {
      onEvent({ kind: "text_final", text: agentResponse });
      onEvent({ kind: "done" });
    });

    render(<App />);

    expect(
      await screen.findByRole("button", { name: "See more" }),
    ).toBeVisible();
    expect(screen.queryByText("Studio reminder")).not.toBeInTheDocument();
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-notifications-open",
      "false",
    );

    fireEvent.click(screen.getByRole("button", { name: "See more" }));
    expect(await screen.findByText("Studio reminder")).toBeVisible();
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-notifications-open",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: /Notifications/ }));
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-mobile-notifications-open",
      "true",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "View details: Studio reminder" }),
    );

    expect(api.streamAgentRun).not.toHaveBeenCalled();
    const presentedCard = await screen.findByRole("article", {
      name: "Communication: Studio reminder",
    });
    expect(
      screen.queryByRole("complementary", { name: "Notification center" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-notifications-open",
      "false",
    );
    expect(
      within(presentedCard).getByText("Bring your prototype to class."),
    ).toBeVisible();
    expect(within(presentedCard).queryByText("View details")).not.toBeInTheDocument();
    const composer = screen.getByRole("textbox", { name: "Message" });
    expect(composer).toHaveAttribute("placeholder", "Ask the agent about this message");
    fireEvent.click(
      within(presentedCard).getByRole("button", { name: "Close message" }),
    );

    expect(
      screen.queryByRole("article", { name: "Communication: Studio reminder" }),
    ).not.toBeInTheDocument();
    expect(api.streamAgentRun).not.toHaveBeenCalled();
    expect(composer).toHaveAttribute(
      "placeholder",
      "Start typing to interact with the agent",
    );
    expect(
      screen.getByRole("complementary", { name: "Notification center" }),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "See more" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "View details: Studio reminder" }),
    );
    const reopenedCard = await screen.findByRole("article", {
      name: "Communication: Studio reminder",
    });
    fireEvent.change(composer, {
      target: { value: "Help me draft a brief reply." },
    });
    fireEvent.keyDown(composer, { key: "Enter" });

    await waitFor(() =>
      expect(api.streamAgentRun).toHaveBeenCalledWith(
        conversation.id,
        expect.stringContaining(actionPrompt),
        expect.any(Function),
        expect.any(AbortSignal),
      ),
    );
    expect(vi.mocked(api.streamAgentRun).mock.calls.at(-1)?.[1]).toContain(
      "Help me draft a brief reply.",
    );
    expect(reopenedCard).toBeVisible();
    const response = await screen.findByText(agentResponse);
    expect(
      reopenedCard.compareDocumentPosition(response) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.click(
      within(reopenedCard).getByRole("button", { name: "Close message" }),
    );
    expect(
      screen.queryByRole("article", { name: "Communication: Studio reminder" }),
    ).not.toBeInTheDocument();
    expect(response).toBeVisible();
    expect(composer).toHaveAttribute(
      "placeholder",
      "Start typing to interact with the agent",
    );
  });

  it("asks the agent for a caught-up greeting on authenticated page load", async () => {
    vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
    vi.mocked(api.listConversations).mockResolvedValue([]);

    render(<App />);

    expect(
      await screen.findByText(
        "Hello. You have no new notifications or upcoming deadlines. We could review the schedule.",
      ),
    ).toBeVisible();
    expect(api.generatePageGreeting).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole("complementary", { name: "Notification center" }),
    ).not.toBeInTheDocument();
  });

  it("retries an interrupted authenticated page greeting without showing the public welcome", async () => {
    vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
    vi.mocked(api.listConversations).mockResolvedValue([]);
    vi.mocked(api.generatePageGreeting)
      .mockRejectedValueOnce(new Error("connection interrupted"))
      .mockResolvedValueOnce({
        output_text: "Hello Alice. Your course updates are ready.",
        event_ids: [],
      });

    render(<App />);

    expect(
      await screen.findByText("Hello Alice. Your course updates are ready."),
    ).toBeVisible();
    expect(api.generatePageGreeting).toHaveBeenCalledTimes(2);
    expect(document.querySelector(".latest-response")).not.toHaveTextContent(
      /Welcome\. I’m the Course Agent/,
    );
  });

  it.each(["MIT", "MIT Media Lab", "New chat"])(
    "starts a fresh chat from the %s header control",
    async (controlName) => {
      vi.useFakeTimers();
      try {
        render(<App />);
        await act(async () => {
          vi.advanceTimersByTime(3_600);
          await Promise.resolve();
          await Promise.resolve();
          await Promise.resolve();
        });
        const composer = screen.getByRole("textbox", { name: "Message" });
        fireEvent.change(composer, { target: { value: "Unsent draft" } });
        fireEvent.click(screen.getByRole("button", { name: controlName }));

        expect(document.querySelector(".latest-response")).toHaveTextContent(
          /Welcome\. I’m the Course Agent/,
        );
        expect(document.querySelector(".latest-response")).toHaveAttribute(
          "data-staggered",
          "true",
        );
        expect(document.querySelector(".latest-response")).toHaveAttribute(
          "data-character-delay",
          "3000",
        );
        expect(composer).toHaveValue("");

        fireEvent.change(composer, { target: { value: "A fresh question" } });
        fireEvent.keyDown(composer, { key: "Enter" });
        expect(api.createConversation).toHaveBeenCalledWith("A fresh question");
      } finally {
        vi.clearAllTimers();
        vi.useRealTimers();
      }
    },
  );

  it.each([
    ["Apply", "I'd like to apply for the course."],
    ["Schedule", "Show me the course schedule."],
    ["Grading", "How is grading handled in this course?"],
  ])("sends the %s shortcut through the agent conversation", async (label, prompt) => {
    render(<App />);
    await openExistingConversation();

    fireEvent.click(screen.getByRole("button", { name: label }));

    await waitFor(() =>
      expect(api.streamAgentRun).toHaveBeenCalledWith(
        conversation.id,
        prompt,
        expect.any(Function),
        expect.any(AbortSignal),
      ),
    );
    if (label === "Apply") {
      expect(api.ensureApplicationDraft).toHaveBeenCalledWith(conversation.id);
      expect(vi.mocked(api.ensureApplicationDraft).mock.invocationCallOrder[0]).toBeLessThan(
        vi.mocked(api.streamAgentRun).mock.invocationCallOrder[0]!,
      );
      expect(screen.getByRole("textbox", { name: "Name" })).toBeInTheDocument();
    } else {
      expect(api.ensureApplicationDraft).not.toHaveBeenCalled();
    }
  });

  it.each([
    ["student", "I'd like to email the course instructors. Help me prepare a question for course staff using the available email tool."],
    ["instructor", "I'd like to contact students. Help me prepare a message using the instructor messaging tool, asking for the audience and message details you need."],
  ] as const)("starts the %s contact workflow through the agent", async (role, prompt) => {
    vi.mocked(api.getPrincipal).mockResolvedValue({
      ...studentPrincipal,
      roles: ["public", role],
    });
    render(<App />);
    await openExistingConversation();

    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
    const contact = screen.getByRole("button", { name: "Contact" });
    const shortcuts = screen.getByRole("navigation", { name: "Course shortcuts" });
    expect(contact).toBe(shortcuts.firstElementChild);
    expect(shortcuts.previousElementSibling).toBe(
      screen.getByRole("button", { name: "New chat" }),
    );
    fireEvent.click(contact);

    await waitFor(() =>
      expect(api.streamAgentRun).toHaveBeenCalledWith(
        conversation.id, prompt, expect.any(Function), expect.any(AbortSignal),
      ),
    );
    expect(api.ensureApplicationDraft).not.toHaveBeenCalled();
    expect(api.confirmTAQuestion).not.toHaveBeenCalled();
    expect(api.confirmInstructorMessage).not.toHaveBeenCalled();
  });

  it("does not open the application draft from typed message text", async () => {
    render(<App />);
    await openExistingConversation();

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "I'd like to apply for the course." } });
    fireEvent.keyDown(composer, { key: "Enter" });

    await waitFor(() =>
      expect(api.streamAgentRun).toHaveBeenCalledWith(
        conversation.id,
        "I'd like to apply for the course.",
        expect.any(Function),
        expect.any(AbortSignal),
      ),
    );
    expect(api.ensureApplicationDraft).not.toHaveBeenCalled();
  });

  it("opens the application draft in the workspace before prompting the agent", async () => {
    render(<App />);
    await openExistingConversation();

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(
      await screen.findByRole("article", { name: "Course Application Draft" }),
    ).toBeInTheDocument();
    expect(api.ensureApplicationDraft).toHaveBeenCalledWith(conversation.id);
    expect(api.streamAgentRun).toHaveBeenCalledWith(
      conversation.id,
      "I'd like to apply for the course.",
      expect.any(Function),
      expect.any(AbortSignal),
    );
  });

  it("keeps New chat available while the workspace is open", async () => {
    render(<App />);
    await openExistingConversation();

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("complementary", { name: "Workspace" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "New chat" }));

    expect(screen.queryByRole("complementary", { name: "Workspace" })).not.toBeInTheDocument();
    expect(document.querySelector(".latest-response")).toHaveTextContent(
      /Welcome\. I’m the Course Agent/,
    );
    expect(screen.getByRole("textbox", { name: "Message" })).toBeEnabled();
  });

  it("returns to the prior conversation after closing the application workspace", async () => {
    render(<App />);
    await openExistingConversation();

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("complementary", { name: "Workspace" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close workspace" }));

    expect(screen.queryByRole("complementary", { name: "Workspace" })).not.toBeInTheDocument();
    expect(screen.getByText("The earlier response.")).toBeInTheDocument();
    expect(screen.getByText("To continue, send a message to the Course Agent.")).toBeInTheDocument();
  });

  it("closes the application workspace after a successful submission", async () => {
    render(<App />);
    await openExistingConversation();

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("complementary", { name: "Workspace" })).toBeInTheDocument();

    const streamCall = vi.mocked(api.streamAgentRun).mock.calls.at(-1);
    const onEvent = streamCall?.[2];
    act(() => {
      onEvent?.({ kind: "application_submitted" });
      onEvent?.({ kind: "text_final", text: "Your application has been submitted." });
    });

    expect(screen.queryByRole("complementary", { name: "Workspace" })).not.toBeInTheDocument();
    expect(screen.getByText("Your application has been submitted.")).toBeInTheDocument();
    expect(api.applyWorkspacePanelAction).toHaveBeenCalledWith(
      conversation.id,
      "close",
      "40000000-0000-4000-8000-000000000009",
    );
  });

  it("shows a disabled composer submission action until application material is complete", async () => {
    vi.mocked(api.ensureApplicationDraft).mockResolvedValue({
      ...previousEvent,
      type: "workspace.panel.opened",
      payload: {
        command: {
          type: "open",
          panel: {
            id: "40000000-0000-4000-8000-000000000010",
            component_id: "draft-document",
            title: "Course Application Draft",
            resource_uri: "course://application",
            props: {
              title: "Course Application Draft",
              fields: [
                { id: "name", label: "Name", status: "missing" },
                { id: "email", label: "Email", status: "missing" },
                { id: "github_id", label: "GitHub ID", status: "missing" },
                {
                  id: "school",
                  label: "School",
                  status: "missing",
                  options: ["MIT Media Lab", "MIT", "Harvard", "Wellesley", "Other"],
                },
                {
                  id: "department",
                  label: "Department",
                  status: "missing",
                },
                {
                  id: "research_group",
                  label: "Research group",
                  status: "missing",
                },
                {
                  id: "degree",
                  label: "Degree",
                  status: "missing",
                },
                {
                  id: "degree_start_year",
                  label: "Year degree started",
                  status: "missing",
                },
                { id: "personal_webpage", label: "Personal Webpage", status: "missing" },
                { id: "interests", label: "Interests", status: "missing" },
                {
                  id: "why_take_this_class",
                  label:
                    "Motivation: why this course; what you have built and want to build; your past project roles",
                  status: "missing",
                },
                { id: "knowledgeable_about", label: "Knowledgeable about", status: "missing" },
                { id: "skill_set", label: "Skill-set", status: "missing" },
                {
                  id: "registration_status",
                  label: "Registration",
                  status: "missing",
                  options: ["for credit", "listener"],
                },
                {
                  id: "listener_willing_to_do_weekly_builds",
                  label: "For listeners: willing to do weekly builds",
                  status: "missing",
                  options: ["yes", "no", "not applicable"],
                },
                {
                  id: "questions_or_comments_for_instructors",
                  label: "Questions or comments for instructors",
                  status: "missing",
                },
                {
                  id: "photo_upload_id",
                  label: "Class-only picture that represents you (JPG/JPEG, PNG, or WebP)",
                  status: "missing",
                },
              ],
            },
            state: {},
          },
        },
      },
    });
    render(<App />);
    await openExistingConversation();

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    const submit = await screen.findByRole("button", { name: "Submit application" });
    expect(submit).toBeDisabled();
    expect(submit.parentElement).toHaveAttribute(
      "title",
      "0/17 required fields confirmed",
    );
  });

  it("shows draft save failures beside the field without replacing them with a generic trace", async () => {
    vi.mocked(api.recordWorkspaceInteraction).mockRejectedValueOnce(
      new Error("Enter at least two characters."),
    );
    render(<App />);
    await openExistingConversation();

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    const name = await screen.findByRole("textbox", { name: "Name" });
    fireEvent.change(name, { target: { value: "A" } });
    fireEvent.blur(name);

    expect(await screen.findByRole("alert")).toHaveTextContent("Enter at least two characters.");
    expect(name).toHaveValue("A");
    expect(screen.queryByText("Workspace interaction was not saved")).not.toBeInTheDocument();
  });

  it("allows only one shortcut operation while an agent run is active", async () => {
    let finishRun = () => {};
    vi.mocked(api.streamAgentRun).mockImplementation(
      async (_id, _text, _onEvent, signal) =>
        new Promise<void>((resolve) => {
          finishRun = resolve;
          signal?.addEventListener("abort", () => resolve());
        }),
    );
    render(<App />);
    await openExistingConversation();

    fireEvent.click(screen.getByRole("button", { name: "Schedule" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(api.streamAgentRun).toHaveBeenCalledTimes(1);
    expect(api.ensureApplicationDraft).not.toHaveBeenCalled();

    finishRun();
  });

  it("replaces the previous response after a new message", async () => {
    vi.mocked(api.streamAgentRun).mockImplementation(async (_id, _text, onEvent) => {
      onEvent({
        kind: "activity",
        activity: {
          kind: "resource",
          label: "Reading course syllabus",
        },
      });
      onEvent({ kind: "text", text: "The new " });
      onEvent({ kind: "text", text: "response." });
      onEvent({ kind: "text_final", text: "The new response." });
      onEvent({ kind: "done" });
    });
    render(<App />);
    await openExistingConversation();

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "What is due?" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    expect(await screen.findByText("The new response.")).toBeInTheDocument();
    expect(screen.queryByText("The earlier response.")).not.toBeInTheDocument();
    expect(api.streamAgentRun).toHaveBeenCalledWith(
      conversation.id,
      "What is due?",
      expect.any(Function),
      expect.any(AbortSignal),
    );
  });

  it("shows frame-coalesced streamed text with an active cursor", async () => {
    let releaseStream = () => {};
    vi.mocked(api.streamAgentRun).mockImplementation(async (_id, _text, onEvent) => {
      onEvent({ kind: "text", text: "Now." });
      await new Promise<void>((resolve) => {
        releaseStream = resolve;
      });
      onEvent({ kind: "text_final", text: "Now done." });
      onEvent({ kind: "done" });
    });
    render(<App />);
    await openExistingConversation();

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "Stream the answer" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    await waitFor(() =>
      expect(document.querySelector(".latest-response")).toHaveTextContent("Now."),
    );
    expect(document.querySelector(".response-character")).not.toBeInTheDocument();
    expect(document.querySelector(".latest-response")).toHaveAttribute(
      "data-streaming",
      "true",
    );
    expect(screen.getByTestId("response-agent-line").parentElement).toHaveClass(
      "response-stage-header",
    );
    const responseStage = screen.getByTestId("response-agent-line").parentElement
      ?.parentElement;
    expect(responseStage).toHaveAttribute("data-scrolled", "false");
    fireEvent.scroll(responseStage!, { target: { scrollTop: 24 } });
    expect(responseStage).toHaveAttribute("data-scrolled", "true");
    fireEvent.scroll(responseStage!, { target: { scrollTop: 0 } });
    expect(responseStage).toHaveAttribute("data-scrolled", "false");
    expect(screen.getByTestId("morphing-line-figure")).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(composer).toBeDisabled();

    releaseStream();
    expect(await screen.findByText("Now done.")).toBeInTheDocument();
    await waitFor(() => expect(composer).not.toBeDisabled());
    expect(screen.getByTestId("morphing-line-figure")).toHaveAttribute(
      "data-active",
      "false",
    );
  });

  it("reveals conversation and account navigation from the history icon", async () => {
    render(<App />);
    await openExistingConversation();

    fireEvent.click(screen.getByRole("button", { name: "Your logs" }));

    expect(screen.getByRole("dialog", { name: "Chat history" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Week one/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Email or username")).toBeInTheDocument();
    expect(screen.getByLabelText("Access code")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide chat history" }));
    expect(screen.queryByRole("dialog", { name: "Chat history" })).not.toBeInTheDocument();
  });

  it.each(["navigation", "direct URL"])(
    "hides notifications on About via %s and restores them on return",
    async (entry) => {
      vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
      vi.mocked(api.getNotificationCenter).mockResolvedValue({
        generated_at: "2026-09-05T12:00:00Z",
        unread_count: 0,
        items: [{
          id: "60000000-0000-4000-8000-000000000021",
          section: "communications",
          kind: "pending_message",
          state: "pending",
          title: "Model choice",
          detail: "May I use a local model?",
          timestamp: "2026-09-05T10:00:00Z",
          due_at: null,
          action_label: "Check status",
          action_prompt: "Check my question.",
          unread: false,
          dismissible: false,
          sender: null,
        }],
      });
      if (entry === "direct URL") window.history.replaceState({}, "", "/about");
      const { container } = render(<App />);
      if (entry === "navigation") {
        expect(await screen.findByRole("complementary", { name: "Notification center" }))
          .toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "About" }));
      }
      expect(await screen.findByRole("heading", {
        level: 1, name: "AI Agents for Cognitive Augmentation",
      })).toBeInTheDocument();
      await waitFor(() => expect(api.getNotificationCenter).toHaveBeenCalled());
      expect(screen.queryByRole("complementary", { name: "Notification center" }))
        .not.toBeInTheDocument();
      expect(container.querySelector(".course-agent"))
        .toHaveAttribute("data-notifications-open", "false");
      expect(container.querySelector(".course-agent"))
        .toHaveAttribute("data-mobile-notifications-open", "false");
      fireEvent.click(screen.getByRole("button", { name: "About" }));
      expect(await screen.findByRole("complementary", { name: "Notification center" }))
        .toBeInTheDocument();
      expect(container.querySelector(".course-agent"))
        .toHaveAttribute("data-notifications-open", "true");
    },
  );

  it("loads About directly from the registered syllabus resource", async () => {
    render(<App />);
    await openExistingConversation();

    fireEvent.click(screen.getByRole("button", { name: "About" }));

    expect(window.location.pathname).toBe("/about");

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "AI Agents for Cognitive Augmentation",
      }),
    ).toBeInTheDocument();
    expect(api.getCourseResourceContent).toHaveBeenCalledWith("course://syllabus");
    expect(screen.getByRole("link", { name: "Download syllabus PDF" })).toHaveAttribute(
      "download", "Course syllabus.pdf",
    );
    expect(screen.getByText("Proposed instructors")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Course Overview" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "35%" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Message" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "About" }));
    expect(await screen.findByRole("textbox", { name: "Message" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");

    fireEvent.click(screen.getByRole("button", { name: "About" }));
    await waitFor(() =>
      expect(api.getCourseResourceContent).toHaveBeenCalledTimes(2),
    );
  });

  it("opens About from its direct URL and follows browser navigation", async () => {
    window.history.replaceState({}, "", "/about");

    render(<App />);

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "AI Agents for Cognitive Augmentation",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Message" })).not.toBeInTheDocument();

    window.history.replaceState({}, "", "/");
    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(await screen.findByRole("textbox", { name: "Message" })).toBeInTheDocument();
  });

  it("creates a conversation from the first loosely composed message", async () => {
    vi.mocked(api.listConversations).mockResolvedValue([]);
    vi.mocked(api.streamAgentRun).mockImplementation(async (_id, _text, onEvent) => {
      onEvent({ kind: "text", text: "Hello." });
    });
    render(<App />);
    await waitFor(() => expect(screen.queryByText("Connecting")).not.toBeInTheDocument());

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "Begin a new idea" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    await screen.findByText("Hello.");
    expect(api.createConversation).toHaveBeenCalledWith("Begin a new idea");
  });

  it("uploads a temporary attachment and gives its receipt to the agent", async () => {
    render(<App />);
    await openExistingConversation();
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    const photo = new File([new Uint8Array([137, 80, 78, 71])], "portrait.png", {
      type: "image/png",
    });

    fireEvent.change(fileInput!, { target: { files: [photo] } });

    expect(await screen.findByText("portrait.png")).toBeInTheDocument();
    expect(api.uploadFile).toHaveBeenCalledWith(photo);
    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "Use this photo for my application" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    await waitFor(() => expect(api.streamAgentRun).toHaveBeenCalled());
    expect(api.streamAgentRun).toHaveBeenCalledWith(
      conversation.id,
      expect.stringContaining(
        "upload_id: 40000000-0000-4000-8000-000000000001",
      ),
      expect.any(Function),
      expect.any(AbortSignal),
    );
  });

  it("accepts dropped files and shows hover and upload states", async () => {
    let finishUpload!: (value: Awaited<ReturnType<typeof api.uploadFile>>) => void;
    vi.mocked(api.uploadFile).mockImplementation(
      () =>
        new Promise((resolve) => {
          finishUpload = resolve;
        }),
    );
    render(<App />);
    await openExistingConversation();
    const app = document.querySelector<HTMLElement>(".course-agent");
    expect(app).not.toBeNull();
    const photo = new File([new Uint8Array([137, 80, 78, 71])], "dropped.png", {
      type: "image/png",
    });
    const dataTransfer = {
      dropEffect: "none",
      files: [photo],
      types: ["Files"],
    };

    fireEvent.dragEnter(app!, { dataTransfer });
    expect(screen.getByText("Drop files to attach")).toBeInTheDocument();
    expect(app).toHaveAttribute("data-file-drag-active", "true");

    fireEvent.drop(app!, { dataTransfer });
    expect(screen.getByText("Uploading 1 file")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeDisabled();
    expect(api.uploadFile).toHaveBeenCalledWith(photo);

    finishUpload({
      id: "40000000-0000-4000-8000-000000000002",
      filename: "dropped.png",
      media_type: "image/png",
      size_bytes: 4,
      created_at: "2026-08-23T10:00:00Z",
      expires_at: "2026-08-24T10:00:00Z",
    });

    expect(await screen.findByText("dropped.png")).toBeInTheDocument();
    expect(screen.queryByText("Uploading 1 file")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).not.toBeDisabled();
  });

  it("rejects an unsupported dropped archive without starting an upload", async () => {
    render(<App />);
    await openExistingConversation();
    const app = document.querySelector<HTMLElement>(".course-agent");
    const archive = new File(["archive"], "materials.zip", {
      type: "application/zip",
    });

    fireEvent.drop(app!, {
      dataTransfer: {
        dropEffect: "none",
        files: [archive],
        types: ["Files"],
      },
    });

    expect(
      await screen.findByText(/“materials\.zip” isn’t supported/),
    ).toBeInTheDocument();
    expect(api.uploadFile).not.toHaveBeenCalled();
    expect(screen.queryByText(/Uploading/)).not.toBeInTheDocument();
  });

  it("welcomes first-time visitors and explains that the agent is the website", async () => {
    vi.mocked(api.listConversations).mockResolvedValue([]);
    render(<App />);

    await waitFor(() =>
      expect(document.querySelector(".latest-response")).toHaveTextContent(
        /This agent is the class website/,
      ),
    );
    expect(document.querySelector(".latest-response")).toHaveTextContent(
      /like to apply/,
    );
    expect(document.querySelector(".latest-response")).toHaveAttribute(
      "data-staggered",
      "true",
    );
  });

  it("keeps the current draft when time passes without a page reload", async () => {
    vi.useFakeTimers();
    try {
      render(<App />);
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(document.querySelector(".latest-response")).toHaveTextContent(
        /Welcome\. I’m the Course Agent/,
      );
      const composer = screen.getByRole("textbox", { name: "Message" });
      fireEvent.change(composer, { target: { value: "An unfinished thought" } });

      act(() => vi.advanceTimersByTime(24 * 60 * 60 * 1000));
      expect(document.querySelector(".latest-response")).toHaveTextContent(
        /Welcome\. I’m the Course Agent/,
      );
      expect(composer).toHaveValue("An unfinished thought");
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });

  it("clears an unfinished composer draft without sending it", async () => {
    render(<App />);
    await openExistingConversation();

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "An unfinished thought" } });
    fireEvent.click(screen.getByRole("button", { name: "Clear draft" }));

    expect(composer).toHaveValue("");
    expect(api.streamAgentRun).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Clear draft" }),
    ).not.toBeInTheDocument();
  });

  it("keeps inspectable agent activity visually separate and expandable", async () => {
    vi.mocked(api.streamAgentRun).mockImplementation(async (_id, _text, onEvent) => {
      onEvent({
        kind: "activity",
        activity: {
          kind: "tool",
          label: "Reading course syllabus",
        },
      });
      onEvent({ kind: "text", text: "Done." });
      onEvent({ kind: "text_final", text: "Done." });
      onEvent({ kind: "done" });
    });
    render(<App />);
    await openExistingConversation();

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "Inspect the course" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    const trace = await screen.findByText("Agent run complete", {
      selector: ".activity-summary-label",
    });
    expect(trace.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByTestId("response-agent-line")).toContainElement(trace);
    expect(screen.getByTestId("response-agent-line").firstElementChild).toHaveTextContent(
      "Course Agent",
    );
    expect(screen.getByRole("banner")).not.toHaveTextContent("Course Agent");
    expect(screen.getByText("Reading course syllabus")).not.toBeVisible();
    fireEvent.click(trace);
    expect(trace.closest("details")).toHaveAttribute("open");
    expect(screen.getByText("Reading course syllabus")).toBeVisible();
    fireEvent.click(trace);
    expect(trace.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("Reading course syllabus")).not.toBeVisible();
  });

  it("opens a validated calendar from the agent stream and persists user close", async () => {
    const panelId = "40000000-0000-4000-8000-000000000001";
    const openCommand = {
      type: "open",
      panel: {
        id: panelId,
        component_id: "calendar",
        title: "Course schedule",
        props: { view: "agenda", focus_date: "2026-10-08" },
        state: {},
      },
    };
    const openedEvent = {
      ...previousEvent,
      id: "30000000-0000-4000-8000-000000000008",
      type: "workspace.panel.opened",
      payload: { command: openCommand },
    };
    vi.mocked(api.getConversation)
      .mockResolvedValueOnce({ conversation, events: [previousEvent] })
      .mockResolvedValueOnce({ conversation, events: [previousEvent, openedEvent] });
    vi.mocked(api.streamAgentRun).mockImplementation(async (_id, _text, onEvent) => {
      onEvent({ kind: "workspace", command: openCommand });
      onEvent({ kind: "text_final", text: "I opened the course schedule." });
      onEvent({ kind: "done" });
    });
    vi.mocked(api.applyWorkspacePanelAction).mockResolvedValue({
      id: "30000000-0000-4000-8000-000000000009",
      schema_version: 1,
      timestamp: "2026-08-24T10:00:00Z",
      type: "workspace.panel.closed",
      actor: "user",
      principal_user_id: null,
      anonymous_session_id: publicPrincipal.anonymous_session_id,
      conversation_id: conversation.id,
      node_id: null,
      payload: { command: { type: "close", panel_id: panelId } },
      metadata: {},
    });
    render(<App />);
    await openExistingConversation();

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "Show me the schedule" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    expect(await screen.findByRole("complementary", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Workspace" })).toHaveAttribute(
      "data-tabbed",
      "false",
    );
    const mobileView = screen.getByRole("group", { name: "Mobile view" });
    const chatView = within(mobileView).getByRole("button", { name: "Chat" });
    const workspaceView = within(mobileView).getByRole("button", {
      name: "Workspace",
    });
    expect(workspaceView).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-mobile-workspace-open",
      "true",
    );
    fireEvent.click(chatView);
    expect(chatView).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-mobile-workspace-open",
      "false",
    );
    fireEvent.click(workspaceView);
    expect(workspaceView).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("tablist", { name: "Workspace panels" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
    expect(api.getCourseResourceContent).toHaveBeenCalledWith(
      "course://schedule",
      expect.any(Function),
    );
    fireEvent.click(await screen.findByRole("button", { name: /Project review/ }));
    await waitFor(() =>
      expect(api.recordWorkspaceInteraction).toHaveBeenCalledWith(
        conversation.id,
        panelId,
        "calendar.select_event",
        "review",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Close workspace" }));
    await waitFor(() =>
      expect(api.applyWorkspacePanelAction).toHaveBeenCalledWith(
        conversation.id,
        "close",
        panelId,
      ),
    );
    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: "Workspace" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
  });

  it("gives the workspace the right-side slot and restores notifications after close", async () => {
    const panelId = "40000000-0000-4000-8000-000000000021";
    const studentConversation = {
      ...conversation,
      user_id: studentPrincipal.user_id,
      anonymous_session_id: null,
    };
    vi.mocked(api.getPrincipal).mockResolvedValue(studentPrincipal);
    vi.mocked(api.listConversations).mockResolvedValue([]);
    vi.mocked(api.createConversation).mockResolvedValue(studentConversation);
    vi.mocked(api.getNotificationCenter).mockResolvedValue({
      generated_at: "2026-09-05T12:00:00Z",
      unread_count: 0,
      items: [
        {
          id: "60000000-0000-4000-8000-000000000021",
          section: "communications",
          kind: "pending_message",
          state: "pending",
          title: "Model choice",
          detail: "May I use a local model?",
          timestamp: "2026-09-05T10:00:00Z",
          due_at: null,
          action_label: "Check status",
          action_prompt: "Check my question.",
          unread: false,
          dismissible: false,
          sender: null,
        },
      ],
    });
    vi.mocked(api.streamAgentRun).mockImplementation(async (_id, _text, onEvent) => {
      onEvent({
        kind: "workspace",
        command: {
          type: "open",
          panel: {
            id: panelId,
            component_id: "calendar",
            title: "Course schedule",
            props: { view: "agenda", focus_date: "2026-10-08" },
            state: {},
          },
        },
      });
      onEvent({ kind: "text_final", text: "I opened the course schedule." });
      onEvent({ kind: "done" });
    });
    vi.mocked(api.getConversation).mockResolvedValue({
      conversation: studentConversation,
      events: [
        {
          ...previousEvent,
          id: "30000000-0000-4000-8000-000000000020",
          type: "workspace.panel.opened",
          principal_user_id: studentPrincipal.user_id,
          anonymous_session_id: null,
          conversation_id: studentConversation.id,
          payload: {
            command: {
              type: "open",
              panel: {
                id: panelId,
                component_id: "calendar",
                title: "Course schedule",
                props: { view: "agenda", focus_date: "2026-10-08" },
                state: {},
              },
            },
          },
        },
      ],
    });
    vi.mocked(api.applyWorkspacePanelAction).mockResolvedValue({
      ...previousEvent,
      id: "30000000-0000-4000-8000-000000000021",
      type: "workspace.panel.closed",
      principal_user_id: studentPrincipal.user_id,
      anonymous_session_id: null,
      conversation_id: studentConversation.id,
      payload: { command: { type: "close", panel_id: panelId } },
    });

    render(<App />);

    expect(
      await screen.findByRole("complementary", { name: "Notification center" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Schedule" }));

    expect(await screen.findByRole("complementary", { name: "Workspace" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Workspace" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.queryByRole("complementary", { name: "Notification center" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-notifications-open",
      "false",
    );

    fireEvent.click(screen.getByRole("button", { name: "Close workspace" }));

    expect(
      await screen.findByRole("complementary", { name: "Notification center" }),
    ).toBeVisible();
    expect(screen.getByText("Model choice")).toBeVisible();
    expect(screen.getByRole("button", { name: "Chat" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /Notifications/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByTestId("course-agent-interface").parentElement).toHaveAttribute(
      "data-notifications-open",
      "true",
    );
  });

  it("replaces the prior workspace panel when a new focus opens", async () => {
    const openEvents = [
      ["40000000-0000-4000-8000-000000000011", "Course schedule"],
      ["40000000-0000-4000-8000-000000000012", "Review dates"],
    ] as const;
    const persistedOpenEvents = openEvents.map(([id, title], index) => ({
      ...previousEvent,
      id: `30000000-0000-4000-8000-00000000003${index}`,
      type: "workspace.panel.opened",
      payload: {
        command: {
          type: "open",
          panel: {
            id,
            component_id: "calendar",
            title,
            props: { view: "agenda" },
            state: {},
          },
        },
      },
    }));
    vi.mocked(api.getConversation)
      .mockResolvedValueOnce({ conversation, events: [previousEvent] })
      .mockResolvedValueOnce({
        conversation,
        events: [previousEvent, ...persistedOpenEvents],
      });
    vi.mocked(api.streamAgentRun).mockImplementation(async (_id, _text, onEvent) => {
      for (const [id, title] of openEvents) {
        onEvent({
          kind: "workspace",
          command: {
            type: "open",
            panel: {
              id,
              component_id: "calendar",
              title,
              props: { view: "agenda" },
              state: {},
            },
          },
        });
      }
      onEvent({ kind: "text_final", text: "The review dates are open." });
      onEvent({ kind: "done" });
    });
    render(<App />);
    await openExistingConversation();

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "Compare the dates" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    const workspace = await screen.findByRole("complementary", { name: "Workspace" });
    expect(workspace).toHaveAttribute("data-tabbed", "false");
    expect(screen.queryByRole("tablist", { name: "Workspace panels" })).not.toBeInTheDocument();

    vi.mocked(api.applyWorkspacePanelAction).mockImplementation(async (_id, _action, panelId) => ({
      ...previousEvent,
      type: "workspace.panel.closed",
      actor: "user",
      payload: { command: { type: "close", panel_id: panelId } },
    }));
    fireEvent.click(screen.getByRole("button", { name: "Close workspace" }));

    await waitFor(() => expect(api.applyWorkspacePanelAction).toHaveBeenCalledTimes(1));
    expect(api.applyWorkspacePanelAction).toHaveBeenCalledWith(
      conversation.id,
      "close",
      "40000000-0000-4000-8000-000000000012",
    );
    expect(await screen.findByRole("button", { name: "Apply" })).toBeInTheDocument();
  });

  it("logs students in from the secondary drawer", async () => {
    render(<App />);
    await openExistingConversation();
    fireEvent.click(screen.getByRole("button", { name: "Your logs" }));
    expect(screen.getByText("Course login")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Email or username"), {
      target: { value: "alice" },
    });
    fireEvent.change(screen.getByLabelText("Access code"), {
      target: { value: "long-secret-code" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() =>
      expect(api.login).toHaveBeenCalledWith("alice", "long-secret-code"),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Chat history" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Contact" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
  });
});
