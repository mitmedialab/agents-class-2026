import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentResponse, responseScale } from "./AgentResponse.js";

describe("AgentResponse", () => {
  it("preserves the large treatment for short responses", () => {
    const { container } = render(<AgentResponse streaming text="A concise answer." />);

    expect(responseScale("A concise answer.")).toBe(1);
    expect(container.firstChild).toHaveAttribute("data-response-scale", "1.000");
    expect(container.firstChild).toHaveAttribute("data-streaming", "true");
    expect(container.querySelector(".response-character")).not.toBeInTheDocument();
    expect(container.firstChild).toHaveTextContent("A concise answer.");
  });

  it("renders safe Markdown resource links and rejects unsafe schemes", () => {
    render(
      <AgentResponse
        text={
          "Review [state transitions](https://example.edu/interaction-states). " +
          "Ignore [unsafe](javascript:alert(1))."
        }
      />,
    );

    expect(screen.getByRole("link", { name: "state transitions" })).toHaveAttribute(
      "href",
      "https://example.edu/interaction-states",
    );
    expect(screen.getByRole("link", { name: "state transitions" })).toHaveAttribute(
      "target",
      "_blank",
    );
    const favicon = document.querySelector<HTMLImageElement>(".response-link-favicon");
    expect(favicon).toHaveAttribute(
      "src",
      "/api/v1/link-favicon?url=https%3A%2F%2Fexample.edu%2Finteraction-states",
    );
    expect(screen.queryByRole("link", { name: "unsafe" })).not.toBeInTheDocument();
    expect(screen.getByText(/Ignore \[unsafe]/)).toBeVisible();
  });

  it("can stagger the standard character animation", () => {
    const { container } = render(
      <AgentResponse
        initialCharacterDelayMs={3000}
        staggerCharacters
        streaming
        text="Agent"
      />,
    );
    const characters = container.querySelectorAll<HTMLElement>(
      ".response-character",
    );

    expect(container.firstChild).toHaveAttribute("data-character-delay", "3000");
    expect(container.firstChild).toHaveAttribute("data-staggered", "true");
    expect(characters[0]).toHaveStyle({ animationDelay: "3000ms" });
    expect(characters[1]).toHaveStyle({ animationDelay: "3014ms" });
    expect(characters[4]).toHaveStyle({ animationDelay: "3056ms" });
  });

  it("keeps the animated word and character layout after the reveal finishes", () => {
    const { container, rerender } = render(
      <AgentResponse staggerCharacters streaming text="Course Agent" />,
    );
    const firstCharacter = container.querySelectorAll(".response-character")[0];

    expect(container.querySelectorAll(".response-word")).toHaveLength(2);
    expect(container.querySelectorAll(".response-character")).toHaveLength(12);

    rerender(<AgentResponse staggerCharacters text="Course Agent" />);

    expect(container.querySelectorAll(".response-word")).toHaveLength(2);
    expect(container.querySelectorAll(".response-character")).toHaveLength(12);
    expect(container.querySelectorAll(".response-character")[0]).toBe(
      firstCharacter,
    );
  });

  it("scales continuously from large responses to the bounded reading size", () => {
    const mediumAnswer = "Course information and application details. ".repeat(6);
    const substantialAnswer = "Course information and application details. ".repeat(14);

    expect(substantialAnswer.length).toBeGreaterThan(520);
    expect(responseScale(mediumAnswer)).toBeGreaterThan(0);
    expect(responseScale(mediumAnswer)).toBeLessThan(1);
    expect(responseScale(substantialAnswer)).toBeLessThan(responseScale(mediumAnswer));
  });

  it("keeps messaging presentations at a stable scroll scale while text streams", () => {
    const { container, rerender } = render(
      <AgentResponse stableScroll streaming text="A private reply is ready." />,
    );
    const response = container.querySelector<HTMLElement>(".latest-response")!;

    expect(response).toHaveAttribute("data-response-layout", "expanded");
    expect(response).toHaveAttribute("data-response-overflow", "true");
    expect(response).toHaveAttribute("data-response-scale", "0.000");
    expect(response).toHaveAttribute("data-response-stable-scroll", "true");

    rerender(
      <AgentResponse
        stableScroll
        streaming
        text="A private reply is ready. Review the complete draft below."
      />,
    );

    expect(response).toHaveAttribute("data-response-scale", "0.000");
    expect(response).toHaveAttribute("data-response-overflow", "true");
  });

  it("uses the largest rendered text scale that fits without scrolling", async () => {
    const clientHeight = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "clientHeight",
    );
    const scrollHeight = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollHeight",
    );
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
      configurable: true,
      get() {
        return this instanceof HTMLElement && this.classList.contains("response-stage")
          ? 300
          : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get() {
        if (!(this instanceof HTMLElement) || !this.classList.contains("response-stage")) {
          return 0;
        }
        const response = this.querySelector<HTMLElement>(".latest-response")!;
        const maximumFontSize = Number.parseFloat(
          response.style.getPropertyValue("--response-font-max"),
        );
        return maximumFontSize > 2.2 ? 500 : 250;
      },
    });

    try {
      const { container } = render(
        <section className="response-stage">
          <AgentResponse text="A response whose rendered display treatment is too tall." />
        </section>,
      );
      const response = container.querySelector<HTMLElement>(".latest-response")!;

      await waitFor(() => expect(response).toHaveAttribute("data-response-fit", "measured"));
      expect(Number(response.dataset.responseScale)).toBeGreaterThan(0.28);
      expect(Number(response.dataset.responseScale)).toBeLessThan(0.31);
      expect(response).toHaveAttribute("data-response-overflow", "false");
    } finally {
      if (clientHeight) {
        Object.defineProperty(HTMLElement.prototype, "clientHeight", clientHeight);
      } else {
        delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight;
      }
      if (scrollHeight) {
        Object.defineProperty(HTMLElement.prototype, "scrollHeight", scrollHeight);
      } else {
        delete (HTMLElement.prototype as { scrollHeight?: number }).scrollHeight;
      }
    }
  });

  it("reclaims header space before enabling parent-surface scrolling", async () => {
    const clientHeight = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "clientHeight",
    );
    const scrollHeight = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollHeight",
    );
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
      configurable: true,
      get() {
        return this instanceof HTMLElement && this.classList.contains("response-stage")
          ? 300
          : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get() {
        if (!(this instanceof HTMLElement) || !this.classList.contains("response-stage")) {
          return 0;
        }
        const response = this.querySelector<HTMLElement>(".latest-response");
        return response?.dataset.responseMeasuring === "expanded" ? 250 : 500;
      },
    });

    try {
      const { container } = render(
        <section className="response-stage">
          <AgentResponse text="A response that fits after fixed header space is reclaimed." />
        </section>,
      );
      const response = container.querySelector<HTMLElement>(".latest-response")!;

      await waitFor(() => expect(response).toHaveAttribute("data-response-fit", "measured"));
      expect(response).toHaveAttribute("data-response-layout", "expanded");
      expect(response).toHaveAttribute("data-response-overflow", "false");
    } finally {
      if (clientHeight) {
        Object.defineProperty(HTMLElement.prototype, "clientHeight", clientHeight);
      } else {
        delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight;
      }
      if (scrollHeight) {
        Object.defineProperty(HTMLElement.prototype, "scrollHeight", scrollHeight);
      } else {
        delete (HTMLElement.prototype as { scrollHeight?: number }).scrollHeight;
      }
    }
  });

  it("marks text that exceeds the minimum reading scale for parent-surface scrolling", async () => {
    const clientHeight = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "clientHeight",
    );
    const scrollHeight = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "scrollHeight",
    );
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
      configurable: true,
      get() {
        return this instanceof HTMLElement && this.classList.contains("response-stage")
          ? 300
          : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get() {
        return this instanceof HTMLElement && this.classList.contains("response-stage")
          ? 500
          : 0;
      },
    });

    try {
      const { container } = render(
        <section className="response-stage">
          <AgentResponse text="A response that remains taller than the complete viewport." />
        </section>,
      );
      const response = container.querySelector<HTMLElement>(".latest-response")!;

      await waitFor(() =>
        expect(response).toHaveAttribute("data-response-overflow", "true"),
      );
      expect(response).toHaveAttribute("data-response-scale", "0.000");
      expect(response).toHaveAttribute("data-response-layout", "expanded");
      expect(response).not.toHaveAttribute("data-response-measuring");
    } finally {
      if (clientHeight) {
        Object.defineProperty(HTMLElement.prototype, "clientHeight", clientHeight);
      } else {
        delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight;
      }
      if (scrollHeight) {
        Object.defineProperty(HTMLElement.prototype, "scrollHeight", scrollHeight);
      } else {
        delete (HTMLElement.prototype as { scrollHeight?: number }).scrollHeight;
      }
    }
  });

  it("observes the stable response stage instead of its rescaled text", () => {
    const originalResizeObserver = globalThis.ResizeObserver;
    const observed: Element[] = [];

    class ResizeObserverMock {
      disconnect() {}
      observe(target: Element) {
        observed.push(target);
      }
      unobserve() {}
    }

    Object.defineProperty(globalThis, "ResizeObserver", {
      configurable: true,
      value: ResizeObserverMock,
      writable: true,
    });

    try {
      const { container } = render(
        <section className="response-stage">
          <div className="response-stage-header">Course Agent activity</div>
          <AgentResponse text="A response that should remain visually stable." />
        </section>,
      );
      const response = container.querySelector<HTMLElement>(".latest-response")!;

      expect(observed).toEqual([response.parentElement]);
      expect(observed).not.toContain(
        container.querySelector(".response-stage-header"),
      );
      expect(observed).not.toContain(response);
    } finally {
      if (originalResizeObserver) {
        Object.defineProperty(globalThis, "ResizeObserver", {
          configurable: true,
          value: originalResizeObserver,
          writable: true,
        });
      } else {
        delete (globalThis as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver;
      }
    }
  });

  it("bounds long responses and renders common markdown structurally", () => {
    const longText = [
      "## Course information",
      "",
      "- **Course focus:** Extensible cognitive agents",
      "- **Format:** Readings and student-built tools",
      "- **Primary course reading:** Jeffrey M. Bradshaw, *An Introduction to Software Agents*—useful background",
      "",
      "Students should understand inspectable agent systems. ".repeat(16),
    ].join("\n");
    const { container } = render(<AgentResponse text={longText} />);

    expect(container.firstChild).toHaveAttribute("data-response-scale", "0.000");
    expect(screen.getByRole("heading", { name: "Course information" })).toBeInTheDocument();
    expect(screen.getByText("Course focus:").tagName).toBe("STRONG");
    expect(screen.getByText("An Introduction to Software Agents").tagName).toBe("EM");
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.queryByText(/\*\*Course focus/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\*An Introduction to Software Agents\*/)).not.toBeInTheDocument();
    expect(container.querySelector(".response-character")).not.toBeInTheDocument();
  });
});
