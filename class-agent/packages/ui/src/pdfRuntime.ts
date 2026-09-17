import type { PDFDocumentLoadingTask } from "pdfjs-dist";

export async function createPdfLoadingTask(
  data: Uint8Array,
): Promise<PDFDocumentLoadingTask> {
  const pdfjs = await import("pdfjs-dist");
  const workerUrl = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default;
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
  return pdfjs.getDocument({ data: data.slice() });
}
