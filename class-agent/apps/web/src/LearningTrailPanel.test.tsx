import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { LearningTrailEntry } from "@class-agent/ui";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api.js";
import * as api from "./api.js";
import { LearningTrailDialog, LearningTrailPanel } from "./LearningTrailPanel.js";

vi.mock("./api.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api.js")>()),
  addLearningTrailFeedback: vi.fn(),
  addStaffLearningTrailFeedback: vi.fn(),
  createLearningTrailEntry: vi.fn(),
  deleteLearningTrailEntry: vi.fn(),
  deleteLearningTrailFeedback: vi.fn(),
  listLearningTrail: vi.fn(),
  listLearningTrailConnections: vi.fn(),
  listLearningTrailStudents: vi.fn(),
  listSharedLearningTrail: vi.fn(),
  updateLearningTrailEntry: vi.fn(),
}));

function entry(overrides: Partial<LearningTrailEntry> = {}): LearningTrailEntry {
  return {
    id: "10000000-0000-4000-8000-000000000001",
    week: 3,
    build_title: "Voice agent",
    build_url: "https://example.com/voice",
    reflection: "Latency mattered more than I expected.",
    still_relevant: true,
    shared_with_staff: false,
    shared_with_class: false,
    feedback: [],
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

const OLDER = entry({
  id: "10000000-0000-4000-8000-000000000002",
  week: 1,
  build_title: "First agent",
  reflection: "Tools were harder than prompts.",
  still_relevant: false,
});

describe("LearningTrailPanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(api.listLearningTrailConnections).mockResolvedValue({});
    vi.mocked(api.createLearningTrailEntry).mockResolvedValue(entry());
    vi.mocked(api.updateLearningTrailEntry).mockResolvedValue(entry());
    vi.mocked(api.addLearningTrailFeedback).mockResolvedValue(entry());
  });

  it("lists every saved build, opens one, and shows the weeks with nothing saved", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([entry(), OLDER]);
    render(<LearningTrailPanel readOnly={false} />);

    const row = await screen.findByRole("button", { name: /^Week 3\s*Voice agent/ });
    expect(screen.getByRole("button", { name: /^Week 1\s*First agent/ })).toHaveTextContent(
      "Not used by the agent",
    );
    expect(screen.getByRole("button", { name: "Add a build for Week 2" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open the build" })).not.toBeInTheDocument();

    fireEvent.click(row);

    expect(screen.getByRole("link", { name: "Open the build" })).toHaveAttribute(
      "href",
      "https://example.com/voice",
    );
  });

  it("asks the agent when requested", async () => {
    const onAsk = vi.fn();
    vi.mocked(api.listLearningTrail).mockResolvedValue([entry()]);
    render(<LearningTrailPanel onAsk={onAsk} readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: "Ask the agent about my next build" }));
    expect(onAsk).toHaveBeenLastCalledWith(expect.stringContaining("my next build"));

    fireEvent.click(screen.getByRole("button", { name: /^Week 3\s*Voice agent/ }));
    fireEvent.click(screen.getByRole("button", { name: "Ask about this week" }));
    expect(onAsk).toHaveBeenLastCalledWith(expect.stringContaining("Week 3 (Voice agent)"));
  });

  it("maps connections, expands one, and follows a build to its own connections", async () => {
    const onAsk = vi.fn();
    vi.mocked(api.listLearningTrail).mockResolvedValue([entry(), OLDER]);
    vi.mocked(api.listLearningTrailConnections).mockResolvedValue({
      [entry().id]: [
        {
          kind: "build",
          target_id: OLDER.id,
          title: "First agent",
          week: 1,
          excerpt: "Tools were harder than prompts.",
          score: 0.31,
          shared_terms: ["tools"],
        },
        {
          kind: "class",
          target_id: "course://slides/week-02",
          title: "Tools, MCPs and Skills",
          excerpt: "Tools let the agent act.",
          score: 0.22,
          shared_terms: ["tools"],
        },
        {
          kind: "classmate",
          target_id: "10000000-0000-4000-8000-000000000009",
          title: "Sam's voice bot",
          week: 3,
          owner_name: "Sam",
          excerpt: "Latency again.",
          score: 0.12,
          shared_terms: ["latency"],
        },
      ],
      [OLDER.id]: [],
    });
    render(<LearningTrailPanel onAsk={onAsk} readOnly={false} />);

    const panel = within(await screen.findByRole("complementary", { name: /Voice agent/ }));
    expect(await panel.findByRole("button", { name: "Show Tools, MCPs and Skills" })).toBeVisible();

    fireEvent.click(panel.getByRole("button", { name: /^Sam's voice bot\s*Sam · Week 3$/, expanded: false }));
    expect(panel.getByText("Sam · Week 3")).toBeInTheDocument();
    expect(panel.getByText("Shared words: latency")).toBeInTheDocument();
    expect(panel.queryByRole("button", { name: "Ask how they connect" })).toBeNull();

    fireEvent.click(panel.getByRole("button", { name: /^Tools, MCPs and Skills$/, expanded: false }));
    fireEvent.click(panel.getByRole("button", { name: "Ask how they connect" }));
    expect(onAsk).toHaveBeenLastCalledWith(expect.stringContaining("course://slides/week-02"));

    fireEvent.click(panel.getByRole("button", { name: /^First agent\s*Week 1$/, expanded: false }));
    fireEvent.click(panel.getByRole("button", { name: "Show its connections" }));
    expect(await screen.findByRole("complementary", { name: /First agent/ })).toBeInTheDocument();
  });

  it("lets the student share an entry with classmates, off by default", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([entry()]);
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /^Week 3\s*Voice agent/ }));
    const box = screen.getByRole("checkbox", { name: /Classmates can see this/ });
    expect(box).not.toBeChecked();
    fireEvent.click(box);

    await waitFor(() =>
      expect(api.updateLearningTrailEntry).toHaveBeenCalledWith(entry().id, {
        shared_with_class: true,
      }),
    );
  });

  it("saves a new reflection and reloads the trail", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValueOnce([]).mockResolvedValue([entry()]);
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: "Add a build" }));
    fireEvent.change(screen.getByLabelText("Week"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("What did you build?"), { target: { value: "Voice agent" } });
    fireEvent.change(screen.getByLabelText("What did you learn, or what would you change?"), {
      target: { value: "Latency mattered." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api.createLearningTrailEntry).toHaveBeenCalledWith({
        week: 3,
        build_title: "Voice agent",
        build_url: null,
        reflection: "Latency mattered.",
        shared_with_staff: true,
        shared_with_class: false,
      }),
    );
    expect(await screen.findByRole("button", { name: /^Week 3\s*Voice agent/ })).toBeInTheDocument();
  });

  it("marks an entry as no longer relevant", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([entry()]);
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /^Week 3\s*Voice agent/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Agent can use this/ }));

    await waitFor(() =>
      expect(api.updateLearningTrailEntry).toHaveBeenCalledWith(entry().id, {
        still_relevant: false,
      }),
    );
  });

  it("lets the student stop sharing an entry with staff", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([entry({ shared_with_staff: true })]);
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /^Week 3\s*Voice agent/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /TAs can see this/ }));

    await waitFor(() =>
      expect(api.updateLearningTrailEntry).toHaveBeenCalledWith(entry().id, {
        shared_with_staff: false,
      }),
    );
  });

  it("does not let a student remove feedback staff wrote", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([
      entry({
        feedback: [
          {
            id: "20000000-0000-4000-8000-000000000002",
            from_role: "instructor",
            from_name: "Pat",
            body: "Strong tradeoff analysis.",
            source: "staff",
            added_at: "2026-10-02T00:00:00Z",
          },
        ],
      }),
    ]);
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /^Week 3\s*Voice agent/ }));
    expect(screen.getByText("Strong tradeoff analysis.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove feedback/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Pasted by you/)).not.toBeInTheDocument();
  });

  it("shows staff the students who shared and sends feedback on an entry", async () => {
    const shared = entry({ shared_with_staff: true });
    const student = {
      student_id: "30000000-0000-4000-8000-000000000003",
      student_name: "Alice Example",
      shared_entries: 1,
      latest_week: 3,
    };
    vi.mocked(api.listLearningTrail).mockRejectedValue(new ApiError("denied", 403));
    vi.mocked(api.listLearningTrailStudents).mockResolvedValue([student]);
    vi.mocked(api.listSharedLearningTrail).mockResolvedValue([shared]);
    vi.mocked(api.addStaffLearningTrailFeedback).mockResolvedValue(shared);
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /Alice Example/ }));
    expect(await screen.findByText(shared.reflection)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Write feedback"), {
      target: { value: "Try streaming." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send to student" }));

    await waitFor(() =>
      expect(api.addStaffLearningTrailFeedback).toHaveBeenCalledWith(
        student.student_id,
        shared.id,
        "Try streaming.",
      ),
    );
  });

  it("attaches pasted feedback and labels where it came from", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([
      entry({
        feedback: [
          {
            id: "20000000-0000-4000-8000-000000000001",
            from_role: "ta",
            from_name: "Sam",
            body: "Try streaming the reply.",
            source: "pasted_by_student",
            added_at: "2026-10-02T00:00:00Z",
          },
        ],
      }),
    ]);
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /^Week 3\s*Voice agent/ }));
    expect(screen.getByText(/TA · Sam · Pasted by you/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add feedback" }));
    fireEvent.change(screen.getByLabelText("Feedback, pasted from the email"), {
      target: { value: "Good work." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save feedback" }));

    await waitFor(() =>
      expect(api.addLearningTrailFeedback).toHaveBeenCalledWith(entry().id, {
        from_role: "ta",
        from_name: null,
        body: "Good work.",
        received_at: null,
      }),
    );
  });

  it("asks for confirmation before deleting", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([entry()]);
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /^Week 3\s*Voice agent/ }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(api.deleteLearningTrailEntry).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(api.deleteLearningTrailEntry).toHaveBeenCalledWith(entry().id));
  });

  it("keeps the form open and reports a failed save", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([]);
    vi.mocked(api.createLearningTrailEntry).mockRejectedValue(new Error("offline"));
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: "Add a build" }));
    fireEvent.change(screen.getByLabelText("Week"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("What did you build?"), { target: { value: "Voice" } });
    fireEvent.change(screen.getByLabelText("What did you learn, or what would you change?"), { target: { value: "Text" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be saved");
    expect(screen.getByLabelText("What did you learn, or what would you change?")).toHaveValue("Text");
  });

  it("offers no changes in a history view", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([entry()]);
    render(<LearningTrailPanel readOnly />);

    fireEvent.click(await screen.findByRole("button", { name: /^Week 3\s*Voice agent/ }));
    expect(screen.getByText(entry().reflection)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a build" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("explains that the trail needs a course login", async () => {
    vi.mocked(api.listLearningTrail).mockRejectedValue(new ApiError("denied", 403));
    vi.mocked(api.listLearningTrailStudents).mockRejectedValue(new ApiError("denied", 403));
    render(<LearningTrailPanel readOnly={false} />);

    expect(await screen.findByText(/course account/)).toBeInTheDocument();
  });

  it("opens without the agent and keeps a draft when Escape is pressed in a field", async () => {
    const onClose = vi.fn();
    vi.mocked(api.listLearningTrail).mockResolvedValue([]);
    render(<LearningTrailDialog onAsk={vi.fn()} onClose={onClose} />);

    fireEvent.click(await screen.findByRole("button", { name: "Add a build" }));
    fireEvent.keyDown(screen.getByLabelText("What did you build?"), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
