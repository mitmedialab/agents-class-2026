import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { LearningTrailEntry } from "@class-agent/ui";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api.js";
import * as api from "./api.js";
import { LearningTrailPanel } from "./LearningTrailPanel.js";

vi.mock("./api.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api.js")>()),
  addLearningTrailFeedback: vi.fn(),
  createLearningTrailEntry: vi.fn(),
  deleteLearningTrailEntry: vi.fn(),
  deleteLearningTrailFeedback: vi.fn(),
  listLearningTrail: vi.fn(),
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
    vi.mocked(api.createLearningTrailEntry).mockResolvedValue(entry());
    vi.mocked(api.updateLearningTrailEntry).mockResolvedValue(entry());
    vi.mocked(api.addLearningTrailFeedback).mockResolvedValue(entry());
  });

  it("shows the most recent reflection and expands the rest from the timeline", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([entry(), OLDER]);
    render(<LearningTrailPanel readOnly={false} />);

    expect(await screen.findByRole("link", { name: "Voice agent" })).toHaveAttribute(
      "href",
      "https://example.com/voice",
    );
    expect(screen.queryByText("Tools were harder than prompts.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View all 2" }));
    fireEvent.click(screen.getByRole("button", { name: /First agent/ }));

    expect(screen.getByText("Tools were harder than prompts.")).toBeInTheDocument();
    expect(screen.getAllByText(/Set aside/).length).toBeGreaterThan(0);
  });

  it("saves a new reflection and reloads the trail", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValueOnce([]).mockResolvedValue([entry()]);
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: "New reflection" }));
    fireEvent.change(screen.getByLabelText("Week"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Build"), { target: { value: "Voice agent" } });
    fireEvent.change(screen.getByLabelText("Reflection"), {
      target: { value: "Latency mattered." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api.createLearningTrailEntry).toHaveBeenCalledWith({
        week: 3,
        build_title: "Voice agent",
        build_url: null,
        reflection: "Latency mattered.",
      }),
    );
    expect(await screen.findByRole("link", { name: "Voice agent" })).toBeInTheDocument();
  });

  it("marks an entry as no longer relevant", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([entry()]);
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Still relevant" }));

    await waitFor(() =>
      expect(api.updateLearningTrailEntry).toHaveBeenCalledWith(entry().id, {
        still_relevant: false,
      }),
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

    expect(await screen.findByText(/TA · Sam · Pasted by you/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add feedback" }));
    fireEvent.change(screen.getByLabelText("Feedback, pasted from the email"), {
      target: { value: "Good work." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Attach" }));

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

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(api.deleteLearningTrailEntry).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(api.deleteLearningTrailEntry).toHaveBeenCalledWith(entry().id));
  });

  it("keeps the form open and reports a failed save", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([]);
    vi.mocked(api.createLearningTrailEntry).mockRejectedValue(new Error("offline"));
    render(<LearningTrailPanel readOnly={false} />);

    fireEvent.click(await screen.findByRole("button", { name: "New reflection" }));
    fireEvent.change(screen.getByLabelText("Week"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Build"), { target: { value: "Voice" } });
    fireEvent.change(screen.getByLabelText("Reflection"), { target: { value: "Text" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be saved");
    expect(screen.getByLabelText("Reflection")).toHaveValue("Text");
  });

  it("offers no changes in a history view", async () => {
    vi.mocked(api.listLearningTrail).mockResolvedValue([entry()]);
    render(<LearningTrailPanel readOnly />);

    expect(await screen.findByRole("link", { name: "Voice agent" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New reflection" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("explains that the trail needs a student login", async () => {
    vi.mocked(api.listLearningTrail).mockRejectedValue(new ApiError("denied", 403));
    render(<LearningTrailPanel readOnly={false} />);

    expect(await screen.findByText(/student account/)).toBeInTheDocument();
  });
});
