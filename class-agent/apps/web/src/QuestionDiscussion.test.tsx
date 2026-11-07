import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuestionDiscussion } from "./QuestionDiscussion.js";
import * as api from "./api.js";

vi.mock("./api.js", () => ({
  getQuestionDiscussion: vi.fn(),
  sendQuestionReply: vi.fn(),
}));

const questionId = "20000000-0000-4000-8000-000000000001";
const discussion: api.QuestionDiscussion = {
  question_id: questionId,
  subject: "Project scope",
  question: "May I use a local model?",
  question_at: "2026-09-15T12:00:00Z",
  answer: "Yes, document the runtime.",
  answer_at: "2026-09-15T13:00:00Z",
  viewer_role: "student",
  student_label: "Student",
  can_reply: true,
  replies: [],
};

describe("question discussion", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getQuestionDiscussion).mockResolvedValue(discussion);
    vi.mocked(api.sendQuestionReply).mockResolvedValue({
      ...discussion,
      replies: [{
        id: "30000000-0000-4000-8000-000000000001",
        sender_role: "student",
        sender_label: "You",
        body: "Would a smaller model work?",
        created_at: "2026-09-15T14:00:00Z",
      }],
    });
  });

  it("sends a follow-up to staff without using the Course Agent composer", async () => {
    render(<QuestionDiscussion questionId={questionId} />);
    expect(await screen.findByText("Yes, document the runtime.")).toBeVisible();
    const input = screen.getByRole("textbox", { name: "Reply to course staff" });
    fireEvent.change(input, { target: { value: "Would a smaller model work?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(api.sendQuestionReply).toHaveBeenCalledWith(
      questionId, "Would a smaller model work?",
    ));
    expect(await screen.findByText("Would a smaller model work?")).toBeVisible();
    expect(input).toHaveValue("");
  });

  it("keeps a failed reply draft available for retry", async () => {
    vi.mocked(api.sendQuestionReply).mockRejectedValueOnce(new Error("Network unavailable"));
    render(<QuestionDiscussion questionId={questionId} />);
    const input = await screen.findByRole("textbox", { name: "Reply to course staff" });
    fireEvent.change(input, { target: { value: "Please clarify." } });
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Network unavailable");
    expect(input).toHaveValue("Please clarify.");
  });
});
