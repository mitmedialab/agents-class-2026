import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MorphingLineFigure } from "./MorphingLineFigure.js";

describe("MorphingLineFigure", () => {
  it("morphs layered contours while active and rests on the square while idle", () => {
    const { container, rerender } = render(<MorphingLineFigure active />);
    const figure = screen.getByTestId("morphing-line-figure");

    expect(figure).toHaveAttribute("aria-hidden", "true");
    expect(figure).toHaveAttribute("data-active", "true");
    expect(container.querySelectorAll("polygon")).toHaveLength(13);
    expect(container.querySelectorAll("animate")).toHaveLength(13);
    expect(container.querySelector("ellipse, rect")).not.toBeInTheDocument();

    rerender(<MorphingLineFigure active={false} />);
    expect(figure).toHaveAttribute("data-active", "false");
    expect(container.querySelectorAll("polygon")).toHaveLength(13);
    expect(container.querySelectorAll("animate")).toHaveLength(0);
  });
});
