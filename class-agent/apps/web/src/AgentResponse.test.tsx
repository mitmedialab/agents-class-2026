import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentResponse, responseScale } from "./AgentResponse.js";

describe("AgentResponse", () => {
  it("preserves the large treatment for short responses", () => {
    const { container } = render(<AgentResponse streaming text="A concise answer." />);

    expect(responseScale("A concise answer.")).toBe(1);
    expect(container.firstChild).toHaveAttribute("data-response-scale", "1.000");
    expect(container.firstChild).toHaveAttribute("data-streaming", "true");
    expect(container.querySelectorAll(".response-character")).toHaveLength(17);
    expect(container.firstChild).toHaveTextContent("A concise answer.");
  });

  it("scales continuously from large responses to the bounded reading size", () => {
    const mediumAnswer = "Course information and application details. ".repeat(6);
    const substantialAnswer = "Course information and application details. ".repeat(14);

    expect(substantialAnswer.length).toBeGreaterThan(520);
    expect(responseScale(mediumAnswer)).toBeGreaterThan(0);
    expect(responseScale(mediumAnswer)).toBeLessThan(1);
    expect(responseScale(substantialAnswer)).toBeLessThan(responseScale(mediumAnswer));
  });

  it("bounds long responses and renders common markdown structurally", () => {
    const longText = [
      "## Course information",
      "",
      "- **Course focus:** Extensible cognitive agents",
      "- **Format:** Readings and student-built tools",
      "",
      "Students should understand inspectable agent systems. ".repeat(16),
    ].join("\n");
    const { container } = render(<AgentResponse text={longText} />);

    expect(container.firstChild).toHaveAttribute("data-response-scale", "0.000");
    expect(screen.getByRole("heading", { name: "Course information" })).toBeInTheDocument();
    expect(screen.getByText("Course focus:").tagName).toBe("STRONG");
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.queryByText(/\*\*Course focus/)).not.toBeInTheDocument();
    expect(container.querySelector(".response-character")).not.toBeInTheDocument();
  });
});
