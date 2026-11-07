import { describe, expect, it } from "vitest";

import { splitWeeklyFeedback } from "./weeklyFeedback.js";

describe("splitWeeklyFeedback", () => {
  it("separates comments from checklist results without scoring them", () => {
    expect(splitWeeklyFeedback(
      "Comments:*\n\nHelpful comments.\n\nGrading Checklist:\n✓ Code link\nx   Agent architecture\n✗ AI disclosure",
    )).toEqual({
      comments: "Helpful comments.",
      checklist: [
        { status: "met", text: "Code link" },
        { status: "unmet", text: "Agent architecture" },
        { status: "unmet", text: "AI disclosure" },
      ],
    });
  });

  it("keeps feedback without a checklist as comments", () => {
    expect(splitWeeklyFeedback("Great work!\n\nKeep going.")).toEqual({
      comments: "Great work!\n\nKeep going.",
      checklist: [],
    });
  });

  it("renders checklist-first TA emails with comments and follow-up separately", () => {
    expect(splitWeeklyFeedback(
      "Grading Checklist:\n• ✓ Tool Implementation\n• ✗ MCP Integration\n\nUnclear or missing:\n• Use of Smolagents\n\nComment: Great work.\n\nReviewer follow-up:\nI found the code later.",
    )).toEqual({
      comments: "Unclear or missing:\n• Use of Smolagents\n\nGreat work.\n\nReviewer follow-up:\nI found the code later.",
      checklist: [
        { status: "met", text: "Tool Implementation" },
        { status: "unmet", text: "MCP Integration" },
      ],
    });
  });
});
