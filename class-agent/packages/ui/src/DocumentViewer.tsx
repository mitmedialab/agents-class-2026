import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export interface DocumentResource {
  uri: string;
  title: string;
  mediaType: string;
  data: Uint8Array;
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

const decoder = new TextDecoder();

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

function MarkdownDocument({ content, range }: { content: string; range: TextRange | null }) {
  let offset = 0;
  return (
    <div className="ca-document-markdown">
      {content.split("\n").map((line, index) => {
        const lineOffset = offset;
        offset += line.length + 1;
        const body = line.replace(/^#{1,3}\s+/, "");
        const bodyOffset = lineOffset + line.length - body.length;
        const value = markedText(body, bodyOffset, range);
        if (/^#\s+/.test(line)) return <h1 key={index}>{value}</h1>;
        if (/^##\s+/.test(line)) return <h2 key={index}>{value}</h2>;
        if (/^###\s+/.test(line)) return <h3 key={index}>{value}</h3>;
        if (/^[-*]\s+/.test(line)) {
          const item = line.replace(/^[-*]\s+/, "");
          return (
            <div className="ca-document-list-item" key={index}>
              <span aria-hidden="true">•</span>
              <span>{markedText(item, lineOffset + line.length - item.length, range)}</span>
            </div>
          );
        }
        if (!line.trim()) return <div className="ca-document-break" key={index} />;
        return <p key={index}>{value}</p>;
      })}
    </div>
  );
}

function SearchBar({
  initialQuery,
  matchCount,
  activeMatch,
  onSubmit,
  onPrevious,
  onNext,
}: {
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
  const [document, setDocument] = useState<import("pdfjs-dist").PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(initialPage);
  const [pageText, setPageText] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setPage(initialPage), [initialPage]);
  useEffect(() => {
    let disposed = false;
    let loaded: import("pdfjs-dist").PDFDocumentProxy | null = null;
    async function load() {
      try {
        const pdfjs = await import("pdfjs-dist");
        const workerUrl = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url"))
          .default;
        pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
        loaded = await pdfjs.getDocument({ data: resource.data.slice() }).promise;
        if (!disposed) setDocument(loaded);
      } catch {
        if (!disposed) setError("This PDF could not be opened.");
      }
    }
    void load();
    return () => {
      disposed = true;
      void loaded?.destroy();
    };
  }, [resource]);

  useEffect(() => {
    if (!document) return;
    const pdfDocument = document;
    let cancelled = false;
    async function renderPage() {
      const safePage = Math.min(Math.max(page, 1), pdfDocument.numPages);
      if (safePage !== page) {
        setPage(safePage);
        return;
      }
      const pdfPage = await pdfDocument.getPage(safePage);
      const viewport = pdfPage.getViewport({ scale: 1.35 });
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (!canvas || !context || cancelled) return;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      await pdfPage.render({
        canvas,
        canvasContext: context,
        viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
      }).promise;
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
    void renderPage().catch(() => setError("This PDF page could not be rendered."));
    return () => {
      cancelled = true;
    };
  }, [document, page]);

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
      <div className="ca-pdf-page">
        <canvas aria-label={`PDF page ${page}`} ref={canvasRef} />
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
    [resource],
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
      <div className="ca-document-content" ref={contentRef}>
        {resource.mediaType === "application/pdf" ? (
          <PdfDocument
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
