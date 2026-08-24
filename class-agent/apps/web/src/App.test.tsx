import type { Conversation, PrincipalContext } from "@class-agent/protocol";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.js";
import * as api from "./api.js";

vi.mock("./api.js", () => ({
  applyWorkspacePanelAction: vi.fn(),
  createConversation: vi.fn(),
  getCourseResourceContent: vi.fn(),
  getConversation: vi.fn(),
  getPrincipal: vi.fn(),
  listConversations: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  recordWorkspaceInteraction: vi.fn(),
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
  vi.mocked(api.getPrincipal).mockResolvedValue(publicPrincipal);
  vi.mocked(api.listConversations).mockResolvedValue([conversation]);
  vi.mocked(api.getConversation).mockResolvedValue({
    conversation,
    events: [previousEvent],
  });
  vi.mocked(api.createConversation).mockResolvedValue(conversation);
  vi.mocked(api.getCourseResourceContent).mockImplementation(async (uri) => {
    if (uri === "course://syllabus") {
      return {
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

describe("Course Agent interface", () => {
  it("shows only the latest agent response in the main workspace", async () => {
    render(<App />);

    expect(await screen.findByText("The earlier response.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "MIT" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "MIT Media Lab" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show chat history" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Schedule" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Grading" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "About" })).toBeInTheDocument();
    expect(screen.getByText("Course Agent")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveAttribute(
      "placeholder",
      "Start typing to interact with the agent",
    );
    expect(screen.getByTestId("workspace-shell")).toBeInTheDocument();
    expect(screen.queryByText("Week one")).not.toBeInTheDocument();
  });

  it.each([
    ["Apply", "I'd like to apply for the course."],
    ["Schedule", "Show me the course schedule."],
    ["Grading", "How is grading handled in this course?"],
  ])("sends the %s shortcut through the agent conversation", async (label, prompt) => {
    render(<App />);
    await screen.findByText("The earlier response.");

    fireEvent.click(screen.getByRole("button", { name: label }));

    await waitFor(() =>
      expect(api.streamAgentRun).toHaveBeenCalledWith(
        conversation.id,
        prompt,
        expect.any(Function),
        expect.any(AbortSignal),
      ),
    );
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
    await screen.findByText("The earlier response.");

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

  it("shows streamed deltas immediately while newly arrived characters fade in", async () => {
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
    await screen.findByText("The earlier response.");

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "Stream the answer" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    await waitFor(() =>
      expect(document.querySelector(".latest-response")).toHaveTextContent("Now."),
    );
    expect(document.querySelectorAll(".response-character")).toHaveLength(4);
    expect(composer).toBeDisabled();

    releaseStream();
    expect(await screen.findByText("Now done.")).toBeInTheDocument();
    await waitFor(() => expect(composer).not.toBeDisabled());
  });

  it("replaces an earlier progress message while appending chunks within each message", async () => {
    let releaseStream = () => {};
    vi.mocked(api.streamAgentRun).mockImplementation(async (_id, _text, onEvent) => {
      onEvent({ kind: "progress", text: "I’m going to read ", replace: true });
      onEvent({ kind: "progress", text: "the syllabus.", replace: false });
      onEvent({ kind: "progress", text: "I found the schedule", replace: true });
      onEvent({ kind: "progress", text: " and I’m checking it.", replace: false });
      await new Promise<void>((resolve) => {
        releaseStream = resolve;
      });
      onEvent({ kind: "text_final", text: "Here is the final answer." });
      onEvent({ kind: "done" });
    });
    render(<App />);
    await screen.findByText("The earlier response.");

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "What is covered?" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    await waitFor(() =>
      expect(screen.queryByText("The earlier response.")).not.toBeInTheDocument(),
    );
    expect(document.querySelector(".latest-response")).toHaveTextContent(
      "I found the schedule and I’m checking it.",
    );
    expect(document.querySelector(".latest-response")).not.toHaveTextContent(
      "I’m going to read the syllabus.",
    );
    expect(
      screen.getByText("Sharing intermediate update", {
        selector: ".activity-summary-label",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Agent activity" })).not.toHaveTextContent(
      "I found the schedule and I’m checking it.",
    );
    expect(composer).toBeDisabled();

    releaseStream();
    expect(await screen.findByText("Here is the final answer.")).toBeInTheDocument();
    expect(document.querySelector(".latest-response")).not.toHaveTextContent(
      "I’m going to read the syllabus.",
    );
    await waitFor(() => expect(composer).not.toBeDisabled());
  });

  it("reveals conversation and account navigation from the history icon", async () => {
    render(<App />);
    await screen.findByText("The earlier response.");

    fireEvent.click(screen.getByRole("button", { name: "Show chat history" }));

    expect(screen.getByRole("dialog", { name: "Chat history" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Week one/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("Access code")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide chat history" }));
    expect(screen.queryByRole("dialog", { name: "Chat history" })).not.toBeInTheDocument();
  });

  it("loads About directly from the registered syllabus resource", async () => {
    render(<App />);
    await screen.findByText("The earlier response.");

    fireEvent.click(screen.getByRole("button", { name: "About" }));

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "AI Agents for Cognitive Augmentation",
      }),
    ).toBeInTheDocument();
    expect(api.getCourseResourceContent).toHaveBeenCalledWith("course://syllabus");
    expect(screen.getByText("Proposed instructors")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Course Overview" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "35%" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Message" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "About" }));
    expect(await screen.findByRole("textbox", { name: "Message" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "About" }));
    await waitFor(() =>
      expect(api.getCourseResourceContent).toHaveBeenCalledTimes(2),
    );
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
    await screen.findByText("The earlier response.");
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

  it("welcomes first-time visitors and explains that the agent is the website", async () => {
    vi.mocked(api.listConversations).mockResolvedValue([]);
    render(<App />);

    expect(
      await screen.findByText(/This agent is the class website/),
    ).toBeInTheDocument();
    expect(screen.getByText(/like to apply/)).toBeInTheDocument();
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
    await screen.findByText("The earlier response.");

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
    expect(screen.getByText("Reading course syllabus")).toBeInTheDocument();
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
    await screen.findByText("The earlier response.");

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "Show me the schedule" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    expect(await screen.findByRole("complementary", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Workspace" })).toHaveAttribute(
      "data-tabbed",
      "false",
    );
    expect(screen.queryByRole("tablist", { name: "Workspace panels" })).not.toBeInTheDocument();
    expect(api.getCourseResourceContent).toHaveBeenCalledWith("course://schedule");
    fireEvent.click(await screen.findByRole("button", { name: /Project review/ }));
    await waitFor(() =>
      expect(api.recordWorkspaceInteraction).toHaveBeenCalledWith(
        conversation.id,
        panelId,
        "calendar.select_event",
        "review",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Close Course schedule" }));
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
  });

  it("shows workspace tabs only when more than one panel is open", async () => {
    vi.mocked(api.streamAgentRun).mockImplementation(async (_id, _text, onEvent) => {
      for (const [id, title] of [
        ["40000000-0000-4000-8000-000000000011", "Course schedule"],
        ["40000000-0000-4000-8000-000000000012", "Review dates"],
      ]) {
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
      onEvent({ kind: "text_final", text: "Both calendars are open." });
      onEvent({ kind: "done" });
    });
    render(<App />);
    await screen.findByText("The earlier response.");

    const composer = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(composer, { target: { value: "Compare the dates" } });
    fireEvent.keyDown(composer, { key: "Enter" });

    const workspace = await screen.findByRole("complementary", { name: "Workspace" });
    expect(workspace).toHaveAttribute("data-tabbed", "true");
    expect(screen.getByRole("tablist", { name: "Workspace panels" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Course schedule" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Review dates" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("logs students in from the secondary drawer", async () => {
    render(<App />);
    await screen.findByText("The earlier response.");
    fireEvent.click(screen.getByRole("button", { name: "Show chat history" }));

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "alice" } });
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
  });
});
