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
});
