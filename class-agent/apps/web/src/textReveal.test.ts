import { describe, expect, it, vi } from "vitest";
import { DEFAULT_REVEAL_INTERVAL_MS, TextRevealQueue } from "./textReveal.js";

describe("TextRevealQueue", () => {
  it("buffers an immediate model result and reveals fifty characters per second", async () => {
    vi.useFakeTimers();
    const frames: string[] = [];
    const queue = new TextRevealQueue((text) => frames.push(text));

    expect(DEFAULT_REVEAL_INTERVAL_MS).toBe(20);

    queue.append("Fast.");
    const finished = queue.finish();

    await vi.advanceTimersByTimeAsync(0);
    expect(frames).toEqual(["F"]);
    await vi.advanceTimersByTimeAsync(20);
    expect(frames.at(-1)).toBe("Fa");
    await vi.advanceTimersByTimeAsync(60);
    expect(frames.at(-1)).toBe("Fast.");
    await finished;
    vi.useRealTimers();
  });

  it("never splits a multi-unit Unicode character", async () => {
    vi.useFakeTimers();
    const frames: string[] = [];
    const queue = new TextRevealQueue((text) => frames.push(text), 20);

    queue.append("A😀B");
    const finished = queue.finish();
    await vi.advanceTimersByTimeAsync(0);
    expect(frames).toEqual(["A"]);
    await vi.advanceTimersByTimeAsync(20);
    expect(frames.at(-1)).toBe("A😀");
    await vi.advanceTimersByTimeAsync(20);
    expect(frames.at(-1)).toBe("A😀B");
    await finished;
    vi.useRealTimers();
  });
});
