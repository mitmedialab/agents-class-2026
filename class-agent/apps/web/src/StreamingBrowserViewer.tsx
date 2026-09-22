import { BrowserViewer } from "@class-agent/ui";
import { useEffect, useState, type ComponentProps } from "react";

interface Frame {
  jpeg: string;
  width: number;
  height: number;
  scroll_y: number;
}

export function parseBrowserFrame(data: string): Frame | null {
  try {
    const value: unknown = JSON.parse(data);
    if (!value || typeof value !== "object") return null;
    const frame = value as Record<string, unknown>;
    if (typeof frame.jpeg !== "string" || frame.jpeg.length > 8_000_000 ||
        !/^[A-Za-z0-9+/]+={0,2}$/.test(frame.jpeg)) return null;
    for (const key of ["width", "height"] as const) {
      if (typeof frame[key] !== "number" || !Number.isInteger(frame[key]) ||
          frame[key] < 1 || frame[key] > 4096) return null;
    }
    if (typeof frame.scroll_y !== "number" || !Number.isSafeInteger(frame.scroll_y) ||
        frame.scroll_y < 0) return null;
    return frame as unknown as Frame;
  } catch {
    return null;
  }
}

export function StreamingBrowserViewer({
  streamUrl, ...props
}: ComponentProps<typeof BrowserViewer> & { streamUrl: string }) {
  const [frame, setFrame] = useState<Frame | null>(null);
  useEffect(() => {
    setFrame(null);
    if (typeof EventSource === "undefined") return;
    const source = new EventSource(streamUrl, { withCredentials: true });
    source.onmessage = event => setFrame(parseBrowserFrame(event.data));
    source.onerror = () => setFrame(null);
    source.addEventListener("unavailable", () => {
      setFrame(null);
      source.close();
    });
    return () => source.close();
  }, [streamUrl]);
  return <BrowserViewer {...props} {...(frame ? { liveFrame: {
    imageUrl: `data:image/jpeg;base64,${frame.jpeg}`,
    width: frame.width, height: frame.height, scrollY: frame.scroll_y,
  } } : {})} />;
}
