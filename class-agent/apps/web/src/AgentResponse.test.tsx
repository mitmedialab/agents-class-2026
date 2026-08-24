import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentResponse, responseDensity } from "./AgentResponse.js";

describe("AgentResponse", () => {
  it("preserves the large treatment for short responses", () => {
    const { container } = render(<AgentResponse streaming text="A concise answer." />);

    expect(responseDensity("A concise answer.")).toBe("short");
    expect(container.firstChild).toHaveAttribute("data-density", "short");
    expect(container.firstChild).toHaveAttribute("data-streaming", "true");
    expect(container.querySelectorAll(".response-character")).toHaveLength(17);
    expect(container.firstChild).toHaveTextContent("A concise answer.");
  });

  it("moves substantial prose into the bounded long-reading treatment", () => {
    const substantialAnswer = "Course information and application details. ".repeat(14);

    expect(substantialAnswer.length).toBeGreaterThan(520);
    expect(responseDensity(substantialAnswer)).toBe("long");
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

    expect(container.firstChild).toHaveAttribute("data-density", "long");
    expect(screen.getByRole("heading", { name: "Course information" })).toBeInTheDocument();
    expect(screen.getByText("Course focus:").tagName).toBe("STRONG");
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.queryByText(/\*\*Course focus/)).not.toBeInTheDocument();
    expect(container.querySelector(".response-character")).not.toBeInTheDocument();
  });
});
