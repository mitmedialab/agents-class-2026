import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const pdf = vi.hoisted(() => {
  const destroy = vi.fn(async () => undefined);
  const createPdfLoadingTask = vi.fn(async () => ({
    destroy,
    promise: Promise.resolve({ numPages: 116 }),
  }));
  return { createPdfLoadingTask, destroy };
});

vi.mock("../../../packages/ui/src/pdfRuntime.js", () => ({
  createPdfLoadingTask: pdf.createPdfLoadingTask,
}));

import { DocumentViewer } from "../../../packages/ui/src/DocumentViewer.js";

describe("PDF document lifecycle", () => {
  it("keeps the loaded document when workspace reconciliation recreates its wrapper", async () => {
    const data = new Uint8Array([37, 80, 68, 70]);
    const { rerender } = render(
      <DocumentViewer
        page={41}
        resource={{
          uri: "course://slides/week-01",
          title: "Week 1 Slides",
          mediaType: "application/pdf",
          data,
        }}
      />,
    );
    await waitFor(() => expect(pdf.createPdfLoadingTask).toHaveBeenCalledOnce());

    rerender(
      <DocumentViewer
        page={41}
        resource={{
          uri: "course://slides/week-01",
          title: "Week 1 Slides",
          mediaType: "application/pdf",
          data,
        }}
      />,
    );

    expect(pdf.createPdfLoadingTask).toHaveBeenCalledOnce();
    expect(pdf.destroy).not.toHaveBeenCalled();
  });
});
