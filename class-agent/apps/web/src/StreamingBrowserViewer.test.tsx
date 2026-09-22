import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BrowserViewer } from "@class-agent/ui";
import { parseBrowserFrame, StreamingBrowserViewer } from "./StreamingBrowserViewer.js";

afterEach(() => vi.unstubAllGlobals());

describe("streaming browser", () => {
  it("validates frame data and dimensions", () => {
    expect(parseBrowserFrame('{"jpeg":"YWJj","width":500,"height":400,"scroll_y":200}'))
      .toEqual({ jpeg: "YWJj", width: 500, height: 400, scroll_y: 200 });
    for (const data of ['null', '{}', '{"jpeg":"javascript:bad","width":500,"height":400,"scroll_y":0}',
      '{"jpeg":"YWJj","width":99999,"height":400,"scroll_y":0}']) {
      expect(parseBrowserFrame(data)).toBeNull();
    }
  });

  it("streams with credentials, falls back on error and closes on unmount", () => {
    const source = { onmessage: null as null | ((event: {data: string}) => void),
      onerror: null as null | (() => void), addEventListener: vi.fn(), close: vi.fn() };
    const EventSourceMock = vi.fn(() => source);
    vi.stubGlobal("EventSource", EventSourceMock);
    const { unmount } = render(<StreamingBrowserViewer streamUrl="/stream" imageUrl="/snapshot"
      title="Example" url="https://example.com" />);
    expect(EventSourceMock).toHaveBeenCalledWith("/stream", { withCredentials: true });
    act(() => source.onmessage?.({ data: '{"jpeg":"YWJj","width":500,"height":400,"scroll_y":200}' }));
    expect(screen.getByAltText("Remote browser showing Example")).toHaveAttribute("src", "data:image/jpeg;base64,YWJj");
    expect(screen.getByText(/Live Chromium stream/)).toBeInTheDocument();
    act(() => source.onerror?.());
    expect(screen.getByAltText("Remote browser showing Example")).toHaveAttribute("src", "/snapshot");
    unmount();
    expect(source.close).toHaveBeenCalledOnce();
  });

  it("maps viewport clicks with frame scroll position and forwards wheel input", async () => {
    const onActivate = vi.fn().mockResolvedValue(undefined);
    const onScroll = vi.fn().mockResolvedValue(undefined);
    render(<BrowserViewer imageUrl="/snapshot" title="Example" url="https://example.com"
      liveFrame={{ imageUrl: "data:image/jpeg;base64,YWJj", width: 1000, height: 800, scrollY: 1200 }}
      onActivate={onActivate} onScroll={onScroll} />);
    const image = screen.getByAltText("Remote browser showing Example");
    vi.spyOn(image, "getBoundingClientRect").mockReturnValue({
      left: 0, top: 0, width: 500, height: 400, right: 500, bottom: 400,
      x: 0, y: 0, toJSON: () => ({}),
    });
    fireEvent.load(image);
    fireEvent.click(image, { clientX: 250, clientY: 200 });
    await waitFor(() => expect(onActivate).toHaveBeenCalledWith(500, 1600));
    fireEvent.wheel(screen.getByRole("region", { name: "Scrollable remote browser image" }), { deltaY: 200 });
    await waitFor(() => expect(onScroll).toHaveBeenCalledWith(200));
  });
  it("waits for panel persistence before resizing and enabling controls", () => {
    const onResize = vi.fn();
    let notify: ((entries: { contentRect: { width: number; height: number } }[]) => void) | undefined;
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: typeof notify) { notify = callback; }
      observe() { notify?.([{contentRect: {width: 600, height: 500}}]); }
      disconnect() {}
    });
    vi.useFakeTimers();
    const props = { imageUrl: "/snapshot", title: "Example", url: "https://example.com", onResize };
    const view = render(<BrowserViewer {...props} controlsEnabled={false} />);
    act(() => vi.advanceTimersByTime(200));
    expect(onResize).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Scroll page down" })).toBeDisabled();
    view.rerender(<BrowserViewer {...props} controlsEnabled />);
    act(() => vi.advanceTimersByTime(200));
    expect(onResize).toHaveBeenCalledWith(600, 500);
    view.unmount();
    vi.useRealTimers();
  });

});
