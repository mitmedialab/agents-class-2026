import { useEffect, useRef, useState } from "react";

export interface BrowserViewerProps {
  imageUrl: string;
  liveFrame?: { imageUrl: string; width: number; height: number; scrollY: number };
  controlsEnabled?: boolean;
  title: string;
  url: string;
  viewportWidth?: number;
  viewportHeight?: number;
  focusScrollY?: number;
  onActivate?: (x: number, y: number) => void | Promise<void>;
  onScroll?: (deltaY: number) => void | Promise<void>;
  onResize?: (width: number, height: number) => void | Promise<void>;
}

export function BrowserViewer({
  imageUrl,
  liveFrame,
  controlsEnabled = true,
  title,
  url,
  viewportWidth = 1280,
  viewportHeight = 800,
  focusScrollY = 0,
  onActivate,
  onScroll,
  onResize,
}: BrowserViewerProps) {
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const canvasRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const live = liveFrame !== undefined;
  const pendingScroll = useRef(0);
  const scrolling = useRef(false);
  const resizeTimer = useRef<number | null>(null);
  const lastRequestedSize = useRef<string | null>(null);
  let hostname = url;
  try {
    hostname = new URL(url).hostname;
  } catch {
    // The workspace registry validates URLs; retain a readable fallback.
  }

  useEffect(() => {
    setLoading(!live);
    setFailed(false);
  }, [imageUrl, live]);

  function focusRemotePosition(behavior: ScrollBehavior) {
    const canvas = canvasRef.current;
    const image = imageRef.current;
    if (live || !canvas || !image || !image.complete || typeof canvas.scrollTo !== "function") return;
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
    if (!controlsEnabled || !canvas || !onResize || typeof ResizeObserver === "undefined") return;
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
  }, [controlsEnabled, onResize, viewportHeight, viewportWidth]);

  async function scroll(deltaY: number) {
    if (!controlsEnabled) return;
    const canvas = canvasRef.current;
    if (!live && !failed && canvas && typeof canvas.scrollBy === "function") {
      canvas.scrollBy({ top: deltaY, behavior: "smooth" });
      return;
    }
    if (!onScroll) return;
    pendingScroll.current = Math.max(-1600, Math.min(1600, pendingScroll.current + deltaY));
    if (scrolling.current) return;
    scrolling.current = true;
    setBusy(true);
    try {
      while (pendingScroll.current !== 0) {
        const delta = pendingScroll.current;
        pendingScroll.current = 0;
        await onScroll(delta);
      }
    } finally {
      scrolling.current = false;
      setBusy(false);
    }
  }

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!controlsEnabled || !canvas || !live) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewportHeight : 1;
      void scroll(Math.round(event.deltaY * unit));
    };
    let touchY: number | null = null;
    const start = (event: TouchEvent) => { touchY = event.touches[0]?.clientY ?? null; };
    const move = (event: TouchEvent) => {
      const y = event.touches[0]?.clientY;
      if (touchY === null || y === undefined) return;
      event.preventDefault();
      void scroll(Math.round(touchY - y));
      touchY = y;
    };
    canvas.addEventListener("wheel", wheel, { passive: false });
    canvas.addEventListener("touchstart", start, { passive: true });
    canvas.addEventListener("touchmove", move, { passive: false });
    return () => {
      canvas.removeEventListener("wheel", wheel);
      canvas.removeEventListener("touchstart", start);
      canvas.removeEventListener("touchmove", move);
    };
  }, [controlsEnabled, live, onScroll, viewportHeight]);

  async function activate(event: React.MouseEvent<HTMLImageElement>) {
    if (!controlsEnabled || !onActivate || busy || failed || loading) return;
    const image = event.currentTarget;
    const bounds = image.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    const sourceWidth = liveFrame?.width ?? (image.naturalWidth || viewportWidth);
    const sourceHeight = liveFrame?.height ?? (image.naturalHeight || viewportHeight);
    const x = Math.max(
      0,
      Math.min(sourceWidth - 1, Math.round(((event.clientX - bounds.left) / bounds.width) * sourceWidth)),
    );
    const y = Math.max(
      0,
      Math.min(sourceHeight - 1, Math.round(((event.clientY - bounds.top) / bounds.height) * sourceHeight)),
    );
    setBusy(true);
    try {
      await onActivate(x, y + (liveFrame?.scrollY ?? 0));
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
            disabled={!controlsEnabled || busy || (failed && !onScroll)}
            onClick={() => void scroll(-640)}
            type="button"
          >
            ↑
          </button>
          <button
            aria-label="Scroll page down"
            disabled={!controlsEnabled || busy || (failed && !onScroll)}
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
        data-live={live ? "true" : undefined}
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
            data-interactive={onActivate ? "true" : undefined}
            draggable={false}
            onError={() => {
              setFailed(true);
              setLoading(false);
            }}
            onLoad={() => {
              setLoading(false);
              requestAnimationFrame(() => focusRemotePosition("auto"));
            }}
            onClick={(event) => void activate(event)}
            ref={imageRef}
            src={liveFrame?.imageUrl ?? imageUrl}
          />
        )}
      </div>
      <p className="ca-browser-status">
        {live ? "Live Chromium stream" : "Browser snapshot"} · click links and controls directly · page state is shared with the agent
      </p>
    </section>
  );
}
