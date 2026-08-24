import { useEffect, useRef, useState } from "react";

export interface BrowserViewerProps {
  imageUrl: string;
  title: string;
  url: string;
  viewportWidth?: number;
  viewportHeight?: number;
  focusScrollY?: number;
  onScroll?: (deltaY: number) => void | Promise<void>;
  onResize?: (width: number, height: number) => void | Promise<void>;
}

export function BrowserViewer({
  imageUrl,
  title,
  url,
  viewportWidth = 1280,
  viewportHeight = 800,
  focusScrollY = 0,
  onScroll,
  onResize,
}: BrowserViewerProps) {
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const canvasRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const resizeTimer = useRef<number | null>(null);
  const lastRequestedSize = useRef<string | null>(null);
  let hostname = url;
  try {
    hostname = new URL(url).hostname;
  } catch {
    // The workspace registry validates URLs; retain a readable fallback.
  }

  useEffect(() => {
    setLoading(true);
    setFailed(false);
  }, [imageUrl]);

  function focusRemotePosition(behavior: ScrollBehavior) {
    const canvas = canvasRef.current;
    const image = imageRef.current;
    if (!canvas || !image || !image.complete || typeof canvas.scrollTo !== "function") return;
    const sourceWidth = image.naturalWidth || viewportWidth;
    const scale = sourceWidth > 0 ? image.clientWidth / sourceWidth : 1;
    canvas.scrollTo({ top: focusScrollY * scale, behavior });
  }

  useEffect(() => {
    const frame = requestAnimationFrame(() => focusRemotePosition("smooth"));
    return () => cancelAnimationFrame(frame);
  }, [focusScrollY, imageUrl, viewportWidth]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !onResize || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const width = Math.round(entry.contentRect.width);
      const height = Math.round(entry.contentRect.height);
      if (width < 320 || height < 240) return;
      if (Math.abs(width - viewportWidth) < 16 && Math.abs(height - viewportHeight) < 16) {
        return;
      }
      const key = `${width}x${height}`;
      if (lastRequestedSize.current === key) return;
      if (resizeTimer.current !== null) window.clearTimeout(resizeTimer.current);
      resizeTimer.current = window.setTimeout(() => {
        lastRequestedSize.current = key;
        void onResize(width, height);
      }, 180);
    });
    observer.observe(canvas);
    return () => {
      observer.disconnect();
      if (resizeTimer.current !== null) window.clearTimeout(resizeTimer.current);
    };
  }, [onResize, viewportHeight, viewportWidth]);

  async function scroll(deltaY: number) {
    const canvas = canvasRef.current;
    if (!failed && canvas && typeof canvas.scrollBy === "function") {
      canvas.scrollBy({ top: deltaY, behavior: "smooth" });
      return;
    }
    if (!onScroll || busy) return;
    setBusy(true);
    try {
      await onScroll(deltaY);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label={title} className="ca-browser-viewer">
      <header className="ca-browser-toolbar">
        <div>
          <strong>{title}</strong>
          <span>{hostname}</span>
        </div>
        <div className="ca-browser-actions">
          <button
            aria-label="Scroll page up"
            disabled={busy || (failed && !onScroll)}
            onClick={() => void scroll(-640)}
            type="button"
          >
            ↑
          </button>
          <button
            aria-label="Scroll page down"
            disabled={busy || (failed && !onScroll)}
            onClick={() => void scroll(640)}
            type="button"
          >
            ↓
          </button>
          <a href={url} rel="noreferrer" target="_blank">
            Open externally
          </a>
        </div>
      </header>
      <div
        aria-label="Scrollable remote browser image"
        className="ca-browser-canvas"
        ref={canvasRef}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "PageDown") {
            event.preventDefault();
            void scroll(640);
          } else if (event.key === "ArrowUp" || event.key === "PageUp") {
            event.preventDefault();
            void scroll(-640);
          }
        }}
        role="region"
        tabIndex={0}
      >
        {loading && !failed ? <span>Loading browser view…</span> : null}
        {failed ? (
          <div className="ca-browser-error">
            <strong>Browser session unavailable</strong>
            <p>The isolated session may have expired. Ask the agent to reopen the page.</p>
          </div>
        ) : (
          <img
            alt={`Remote browser showing ${title}`}
            draggable={false}
            onError={() => {
              setFailed(true);
              setLoading(false);
            }}
            onLoad={() => {
              setLoading(false);
              requestAnimationFrame(() => focusRemotePosition("auto"));
            }}
            ref={imageRef}
            src={imageUrl}
          />
        )}
      </div>
      <p className="ca-browser-status">
        Isolated read-only session · content is rendered on the Course Agent server
      </p>
    </section>
  );
}
