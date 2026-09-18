import { DocumentViewer } from "@class-agent/ui";
import { render, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const pdf = vi.hoisted(() => ({ getDocument: vi.fn() }));
vi.mock("../../../packages/ui/node_modules/pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerSrc: "" },
  getDocument: pdf.getDocument,
}));
vi.mock("../../../packages/ui/node_modules/pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "worker.js" }));

it("preserves the PDF loading task across metadata updates and replaces it for new bytes", async () => {
  const firstDestroy = vi.fn();
  const secondDestroy = vi.fn();
  pdf.getDocument
    .mockReturnValueOnce({ promise: Promise.resolve({ numPages: 2 }), destroy: firstDestroy })
    .mockReturnValueOnce({ promise: Promise.resolve({ numPages: 3 }), destroy: secondDestroy });
  const resource = {
    uri: "course://slides/week-01", title: "Slides",
    mediaType: "application/pdf", data: new Uint8Array([1, 2]),
  };
  const view = render(<DocumentViewer resource={resource} />);
  await waitFor(() => expect(pdf.getDocument).toHaveBeenCalledTimes(1));
  view.rerender(<DocumentViewer resource={{ ...resource, title: "Lecture title" }} page={2} />);
  expect(firstDestroy).not.toHaveBeenCalled();
  expect(pdf.getDocument).toHaveBeenCalledTimes(1);
  view.rerender(<DocumentViewer resource={{ ...resource, data: new Uint8Array([3]) }} />);
  await waitFor(() => expect(pdf.getDocument).toHaveBeenCalledTimes(2));
  expect(firstDestroy).toHaveBeenCalledTimes(1);
  view.unmount();
  expect(secondDestroy).toHaveBeenCalledTimes(1);
});

it("downloads the original PDF bytes with a safe filename and releases the URL", async () => {
  const createObjectURL = vi.fn((_blob: Blob) => "blob:lecture-download");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL }));
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  pdf.getDocument.mockReturnValue({ promise: Promise.resolve({ numPages: 2 }), destroy: vi.fn() });
  const bytes = new Uint8Array([37, 80, 68, 70]);
  const view = render(<DocumentViewer resource={{
    uri: "course://slides/week-01", title: "Lecture: AI/Agents",
    mediaType: "application/pdf", data: bytes,
  }} />);
  const downloadButton = view.getByRole("button", { name: "Download PDF" });
  expect(downloadButton.querySelector("svg")).not.toBeNull();
  expect(downloadButton.nextElementSibling?.querySelector("input")).toHaveAttribute("placeholder", "Find");
  downloadButton.click();
  expect(createObjectURL).toHaveBeenCalledTimes(1);
  const blob = createObjectURL.mock.calls[0]?.[0] as unknown as Blob;
  expect(blob.type).toBe("application/pdf");
  expect(blob.size).toBe(bytes.length);
  expect(await new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.readAsArrayBuffer(blob);
  })).toEqual(bytes);
  const link = click.mock.instances[0] as unknown as HTMLAnchorElement;
  expect(link.href).toBe("blob:lecture-download");
  expect(link.download).toBe("Lecture- AI-Agents.pdf");
  view.unmount();
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:lecture-download");
  click.mockRestore();
  vi.unstubAllGlobals();
});
