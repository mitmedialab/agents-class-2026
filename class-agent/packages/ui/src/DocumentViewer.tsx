import { PdfDownload } from "./PdfDownload.js";
import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPdfLoadingTask } from "./pdfRuntime.js";

export interface DocumentResource {
  uri: string;
  title: string;
  mediaType: string;
  data: Uint8Array;
  pdfDownloadUrl?: string;
}

export interface TextHighlightAnchor {
  resourceUri: string;
  page: number;
  quote: string;
  prefix?: string;
  suffix?: string;
}

export interface DocumentViewerProps {
  resource: DocumentResource;
  page?: number | undefined;
  findText?: string | undefined;
  highlight?: TextHighlightAnchor | undefined;
  onPageChange?: ((page: number) => void) | undefined;
  onFind?: ((query: string) => void) | undefined;
}

interface TextRange {
  start: number;
  end: number;
}

interface PdfPageFit {
  scale: number;
  width: number;
  height: number;
}

const decoder = new TextDecoder();

export function fitPdfPageToArea(
  pageWidth: number,
  pageHeight: number,
  areaWidth: number,
  areaHeight: number,
): PdfPageFit | null {
  if (
    !Number.isFinite(pageWidth) ||
    !Number.isFinite(pageHeight) ||
    !Number.isFinite(areaWidth) ||
    !Number.isFinite(areaHeight) ||
    pageWidth <= 0 ||
    pageHeight <= 0 ||
    areaWidth <= 0 ||
    areaHeight <= 0
  ) {
    return null;
  }
  const scale = Math.min(areaWidth / pageWidth, areaHeight / pageHeight);
  return {
    scale,
    width: Math.max(1, Math.min(areaWidth, Math.floor(pageWidth * scale))),
    height: Math.max(1, Math.min(areaHeight, Math.floor(pageHeight * scale))),
  };
}

/** Swap a completed PDF render into the visible canvas without exposing an empty frame. */
export function commitPdfCanvas(
  renderedCanvas: HTMLCanvasElement,
  visibleCanvas: HTMLCanvasElement,
  fit: PdfPageFit,
): boolean {
  const context = visibleCanvas.getContext("2d");
  if (!context) return false;
  visibleCanvas.width = renderedCanvas.width;
  visibleCanvas.height = renderedCanvas.height;
  visibleCanvas.style.width = `${fit.width}px`;
  visibleCanvas.style.height = `${fit.height}px`;
  context.drawImage(renderedCanvas, 0, 0);
  return true;
}

function occurrences(content: string, query: string): TextRange[] {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return [];
  const haystack = content.toLocaleLowerCase();
  const ranges: TextRange[] = [];
  let cursor = 0;
  while (cursor < haystack.length) {
    const start = haystack.indexOf(needle, cursor);
    if (start < 0) break;
    ranges.push({ start, end: start + needle.length });
    cursor = start + Math.max(needle.length, 1);
  }
  return ranges;
}

export function resolveTextAnchor(
  content: string,
  anchor: TextHighlightAnchor,
): TextRange | null {
  const candidates = occurrences(content, anchor.quote);
  if (candidates.length === 0) return null;
  if (!anchor.prefix && !anchor.suffix) return candidates[0] ?? null;
  const normalized = content.toLocaleLowerCase();
  const prefix = anchor.prefix?.toLocaleLowerCase();
  const suffix = anchor.suffix?.toLocaleLowerCase();
  return (
    candidates.find((candidate) => {
      const before = normalized.slice(0, candidate.start).trimEnd();
      const after = normalized.slice(candidate.end).trimStart();
      return (!prefix || before.endsWith(prefix)) && (!suffix || after.startsWith(suffix));
    }) ??
    candidates[0] ??
    null
  );
}

function markedText(text: string, offset: number, activeRange: TextRange | null): ReactNode {
  if (!activeRange) return text;
  const localStart = Math.max(0, activeRange.start - offset);
  const localEnd = Math.min(text.length, activeRange.end - offset);
  if (localStart >= localEnd) return text;
  return (
    <>
      {text.slice(0, localStart)}
      <mark data-document-highlight="true">{text.slice(localStart, localEnd)}</mark>
      {text.slice(localEnd)}
    </>
  );
}

function plainMarkdown(text: string): string {
  return text.replaceAll(/\\([\\`*{}\[\]()#+\-.!_>])/g, "$1");
}

function safeMarkdownHref(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

function inlineMarkdown(
  text: string,
  offset: number,
  range: TextRange | null,
  keyPrefix: string,
): ReactNode[] {
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let partIndex = 0;

  for (const match of text.matchAll(pattern)) {
    const start = match.index;
    if (start > cursor) {
      const plain = text.slice(cursor, start);
      nodes.push(
        <span key={`${keyPrefix}-${partIndex++}`}>
          {markedText(plainMarkdown(plain), offset + cursor, range)}
        </span>,
      );
    }
    const raw = match[0];
    const key = `${keyPrefix}-${partIndex++}`;
    if (raw.startsWith("**") && raw.endsWith("**")) {
      const value = plainMarkdown(raw.slice(2, -2));
      nodes.push(<strong key={key}>{markedText(value, offset + start + 2, range)}</strong>);
    } else if (raw.startsWith("*") && raw.endsWith("*")) {
      const value = plainMarkdown(raw.slice(1, -1));
      nodes.push(<em key={key}>{markedText(value, offset + start + 1, range)}</em>);
    } else if (raw.startsWith("`") && raw.endsWith("`")) {
      const value = raw.slice(1, -1);
      nodes.push(<code key={key}>{markedText(value, offset + start + 1, range)}</code>);
    } else {
      const link = /^\[([^\]]+)]\(([^)]+)\)$/.exec(raw);
      const label = plainMarkdown(link?.[1] ?? raw);
      const href = link?.[2] ? safeMarkdownHref(link[2]) : null;
      nodes.push(
        href ? (
          <a href={href} key={key} rel="noreferrer" target="_blank">
            {markedText(label, offset + start + 1, range)}
          </a>
        ) : (
          <span key={key}>{markedText(label, offset + start, range)}</span>
        ),
      );
    }
    cursor = start + raw.length;
  }
  if (cursor < text.length) {
    const plain = text.slice(cursor);
    nodes.push(
      <span key={`${keyPrefix}-${partIndex}`}>
        {markedText(plainMarkdown(plain), offset + cursor, range)}
      </span>,
    );
  }
  return nodes;
}

function MarkdownDocument({ content, range }: { content: string; range: TextRange | null }) {
  const lines = content.split("\n");
  const offsets: number[] = [];
  let offset = 0;
  for (const line of lines) {
    offsets.push(offset);
    offset += line.length + 1;
  }
  const blocks: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index] ?? "";
    const trimmed = line.trim();
    if (!trimmed) {
      index += 1;
      continue;
    }
    const lineOffset = (offsets[index] ?? 0) + line.indexOf(trimmed);
    const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed);
    if (heading?.[2]) {
      const level = heading[1]?.length ?? 2;
      const bodyOffset = lineOffset + level + 1;
      const value = inlineMarkdown(heading[2], bodyOffset, range, `heading-${index}`);
      blocks.push(
        level === 1 ? (
          <h1 key={`heading-${index}`}>{value}</h1>
        ) : level === 2 ? (
          <h2 key={`heading-${index}`}>{value}</h2>
        ) : (
          <h3 key={`heading-${index}`}>{value}</h3>
        ),
      );
      index += 1;
      continue;
    }
    if (/^[-*]\s+/.test(trimmed)) {
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const candidate = lines[index] ?? "";
        const candidateTrimmed = candidate.trim();
        const item = /^[-*]\s+(.+)$/.exec(candidateTrimmed);
        if (!item?.[1]) break;
        const candidateOffset =
          (offsets[index] ?? 0) + candidate.indexOf(candidateTrimmed) + 2;
        items.push(
          <li key={`bullet-${index}`}>
            {inlineMarkdown(item[1], candidateOffset, range, `bullet-${index}`)}
          </li>,
        );
        index += 1;
      }
      blocks.push(<ul key={`bullets-${index}`}>{items}</ul>);
      continue;
    }
    if (/^\d+[.)]\s+/.test(trimmed)) {
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const candidate = lines[index] ?? "";
        const candidateTrimmed = candidate.trim();
        const item = /^(\d+[.)]\s+)(.+)$/.exec(candidateTrimmed);
        if (!item?.[2]) break;
        const candidateOffset =
          (offsets[index] ?? 0) + candidate.indexOf(candidateTrimmed) + (item[1]?.length ?? 0);
        items.push(
          <li key={`number-${index}`}>
            {inlineMarkdown(item[2], candidateOffset, range, `number-${index}`)}
          </li>,
        );
        index += 1;
      }
      blocks.push(<ol key={`numbers-${index}`}>{items}</ol>);
      continue;
    }
    const paragraph: ReactNode[] = [];
    while (index < lines.length) {
      const candidate = lines[index] ?? "";
      const candidateTrimmed = candidate.trim();
      if (
        !candidateTrimmed ||
        /^#{1,3}\s+/.test(candidateTrimmed) ||
        /^[-*]\s+/.test(candidateTrimmed) ||
        /^\d+[.)]\s+/.test(candidateTrimmed)
      ) {
        break;
      }
      if (paragraph.length) paragraph.push(" ");
      paragraph.push(
        ...inlineMarkdown(
          candidateTrimmed,
          (offsets[index] ?? 0) + candidate.indexOf(candidateTrimmed),
          range,
          `paragraph-${index}`,
        ),
      );
      index += 1;
    }
    blocks.push(<p key={`paragraph-${index}`}>{paragraph}</p>);
  }
  return <div className="ca-document-markdown">{blocks}</div>;
}

function SearchBar({
  initialQuery,
  matchCount,
  activeMatch,
  onSubmit,
  onPrevious,
  onNext,
  leadingControl,
}: {
  leadingControl?: ReactNode;
  initialQuery: string;
  matchCount: number;
  activeMatch: number;
  onSubmit: (query: string) => void;
  onPrevious: () => void;
  onNext: () => void;
}) {
  const [query, setQuery] = useState(initialQuery);
  useEffect(() => setQuery(initialQuery), [initialQuery]);
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit(query);
  }
  return (
    <form className="ca-document-search" onSubmit={submit}>
      {leadingControl}
      <label>
        <span className="ca-visually-hidden">Find in document</span>
        <input
          aria-label="Find in document"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Find"
          type="search"
          value={query}
        />
      </label>
      <span aria-live="polite" className="ca-document-match-count">
        {matchCount ? `${activeMatch + 1} / ${matchCount}` : "No matches"}
      </span>
      <button aria-label="Previous match" disabled={!matchCount} onClick={onPrevious} type="button">
        ↑
      </button>
      <button aria-label="Next match" disabled={!matchCount} onClick={onNext} type="button">
        ↓
      </button>
    </form>
  );
}

function PdfDocument({
  resource,
  initialPage,
  query,
  highlight,
  onPageChange,
}: {
  resource: DocumentResource;
  initialPage: number;
  query: string;
  highlight: TextHighlightAnchor | undefined;
  onPageChange: ((page: number) => void) | undefined;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pageAreaRef = useRef<HTMLDivElement>(null);
  const [document, setDocument] = useState<import("pdfjs-dist").PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(initialPage);
  const [pageText, setPageText] = useState("");
  const [pageArea, setPageArea] = useState({ width: 0, height: 0 });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setPage(initialPage), [initialPage]);
  useEffect(() => {
    const element = pageAreaRef.current;
    if (!element) return;
    const observedElement = element;

    function updateSize(width: number, height: number) {
      const next = {
        width: Math.floor(width),
        height: Math.floor(height),
      };
      if (next.width < 1 || next.height < 1) return;
      setPageArea((current) =>
        current.width === next.width && current.height === next.height ? current : next,
      );
    }

    function measure() {
      updateSize(observedElement.clientWidth, observedElement.clientHeight);
    }

    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(([entry]) => {
            if (entry) updateSize(entry.contentRect.width, entry.contentRect.height);
          });
    observer?.observe(observedElement);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);
  useEffect(() => {
    let disposed = false;
    let loadingTask: import("pdfjs-dist").PDFDocumentLoadingTask | null = null;
    setDocument(null);
    setPageText("");
    setError(null);
    async function load() {
      try {
        loadingTask = await createPdfLoadingTask(resource.data);
        const loaded = await loadingTask.promise;
        if (!disposed) setDocument(loaded);
      } catch {
        if (!disposed) setError("This PDF could not be opened.");
      }
    }
    void load();
    return () => {
      disposed = true;
      void loadingTask?.destroy();
    };
    // Metadata wrappers change during workspace updates; only new bytes or URI reload the PDF.
  }, [resource.data, resource.uri]);

  useEffect(() => {
    if (!document || pageArea.width < 1 || pageArea.height < 1) return;
    const pdfDocument = document;
    let cancelled = false;
    let renderTask: import("pdfjs-dist").RenderTask | null = null;
    async function renderPage() {
      const safePage = Math.min(Math.max(page, 1), pdfDocument.numPages);
      if (safePage !== page) {
        setPage(safePage);
        return;
      }
      const pdfPage = await pdfDocument.getPage(safePage);
      const unscaledViewport = pdfPage.getViewport({ scale: 1 });
      const fit = fitPdfPageToArea(
        unscaledViewport.width,
        unscaledViewport.height,
        pageArea.width,
        pageArea.height,
      );
      if (!fit || cancelled) return;
      const viewport = pdfPage.getViewport({ scale: fit.scale });
      const renderedCanvas = window.document.createElement("canvas");
      const context = renderedCanvas.getContext("2d");
      if (!context || cancelled) return;
      const ratio = window.devicePixelRatio || 1;
      renderedCanvas.width = Math.max(1, Math.floor(viewport.width * ratio));
      renderedCanvas.height = Math.max(1, Math.floor(viewport.height * ratio));
      renderTask = pdfPage.render({
        canvas: renderedCanvas,
        canvasContext: context,
        viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
      });
      await renderTask.promise;
      const visibleCanvas = canvasRef.current;
      if (cancelled || !visibleCanvas || !commitPdfCanvas(renderedCanvas, visibleCanvas, fit)) {
        return;
      }
      const text = await pdfPage.getTextContent();
      if (!cancelled) {
        setPageText(
          text.items
            .map((item) => ("str" in item ? item.str : ""))
            .filter(Boolean)
            .join(" "),
        );
      }
    }
    void renderPage().catch((cause: unknown) => {
      if (
        !cancelled &&
        (!(cause instanceof Error) || cause.name !== "RenderingCancelledException")
      ) {
        setError("This PDF page could not be rendered.");
      }
    });
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [document, page, pageArea]);

  const activeRange = useMemo(() => {
    if (query.trim()) return occurrences(pageText, query)[0] ?? null;
    if (highlight && highlight.page === page) return resolveTextAnchor(pageText, highlight);
    return null;
  }, [highlight, page, pageText, query]);

  if (error) return <p className="ca-document-error">{error}</p>;
  return (
    <div className="ca-pdf-viewer">
      <div className="ca-pdf-pagination">
        <button
          disabled={page <= 1}
          onClick={() => {
            const next = page - 1;
            setPage(next);
            onPageChange?.(next);
          }}
          type="button"
        >
          Previous
        </button>
        <span>
          Page {page} {document ? `of ${document.numPages}` : ""}
        </span>
        <button
          disabled={!document || page >= document.numPages}
          onClick={() => {
            const next = page + 1;
            setPage(next);
            onPageChange?.(next);
          }}
          type="button"
        >
          Next
        </button>
      </div>
      <div className="ca-pdf-stage" ref={pageAreaRef}>
        <div className="ca-pdf-page">
          <canvas aria-label={`PDF page ${page}`} ref={canvasRef} />
        </div>
      </div>
      {pageText ? (
        <details className="ca-pdf-text" open={Boolean(activeRange)}>
          <summary>Accessible page text</summary>
          <p>{markedText(pageText, 0, activeRange)}</p>
        </details>
      ) : null}
    </div>
  );
}

export function DocumentViewer({
  resource,
  page = 1,
  findText = "",
  highlight,
  onPageChange,
  onFind,
}: DocumentViewerProps) {
  const [query, setQuery] = useState(findText);
  const [activeMatch, setActiveMatch] = useState(0);
  const content = useMemo(
    () => (resource.mediaType === "application/pdf" ? "" : decoder.decode(resource.data)),
    [resource.data, resource.mediaType],
  );
  const matches = useMemo(() => occurrences(content, query), [content, query]);
  const anchoredRange = useMemo(
    () =>
      highlight && highlight.resourceUri === resource.uri
        ? resolveTextAnchor(content, highlight)
        : null,
    [content, highlight, resource.uri],
  );
  const activeRange = query.trim() ? (matches[activeMatch] ?? null) : anchoredRange;
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setQuery(findText);
    setActiveMatch(0);
  }, [findText]);
  useEffect(() => {
    contentRef.current
      ?.querySelector<HTMLElement>("[data-document-highlight='true']")
      ?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [activeMatch, activeRange]);

  function submitSearch(nextQuery: string) {
    setQuery(nextQuery);
    setActiveMatch(0);
    onFind?.(nextQuery);
  }

  return (
    <section aria-label={resource.title} className="ca-document-viewer">
      <header className="ca-viewer-toolbar">
        <div>
          <strong>{resource.title}</strong>
          <span>{resource.mediaType}</span>
        </div>
        <SearchBar
          leadingControl={
            resource.mediaType === "application/pdf" || resource.pdfDownloadUrl ? (
              <PdfDownload title={resource.title} href={resource.pdfDownloadUrl}
                data={resource.mediaType === "application/pdf" ? resource.data : undefined} />
            ) : null
          }
          activeMatch={activeMatch}
          initialQuery={query}
          matchCount={matches.length}
          onNext={() => setActiveMatch((current) => (current + 1) % matches.length)}
          onPrevious={() =>
            setActiveMatch((current) => (current - 1 + matches.length) % matches.length)
          }
          onSubmit={submitSearch}
        />
      </header>
      <div
        className="ca-document-content"
        data-media-type={resource.mediaType}
        ref={contentRef}
      >
        {resource.mediaType === "application/pdf" ? (
          <PdfDocument
            key={resource.uri}
            highlight={highlight}
            initialPage={page}
            onPageChange={onPageChange}
            query={query}
            resource={resource}
          />
        ) : resource.mediaType === "text/markdown" ? (
          <MarkdownDocument content={content} range={activeRange} />
        ) : (
          <pre>{markedText(content, 0, activeRange)}</pre>
        )}
      </div>
    </section>
  );
}
