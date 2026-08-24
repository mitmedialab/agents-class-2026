export const DEFAULT_REVEAL_INTERVAL_MS = Math.round(1000 / 50);

type FrameHandler = (text: string, active: boolean) => void;

function nextUnitEnd(text: string, start: number, finalized: boolean): number | null {
  if (start >= text.length) return null;
  const firstCodeUnit = text.charCodeAt(start);
  const isHighSurrogate = firstCodeUnit >= 0xd800 && firstCodeUnit <= 0xdbff;
  if (isHighSurrogate && start + 1 === text.length && !finalized) return null;
  return start + (isHighSurrogate && start + 1 < text.length ? 2 : 1);
}

/**
 * Buffers native provider deltas and reveals Unicode characters at a stable
 * visual cadence. It never delays or backpressures the model/network stream.
 */
export class TextRevealQueue {
  private readonly finishedPromise: Promise<void>;
  private readonly onFrame: FrameHandler;
  private readonly intervalMs: number;
  private source = "";
  private position = 0;
  private finalized = false;
  private settled = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private resolveFinished: (() => void) | null = null;

  constructor(onFrame: FrameHandler, intervalMs = DEFAULT_REVEAL_INTERVAL_MS) {
    this.onFrame = onFrame;
    this.intervalMs = intervalMs;
    this.finishedPromise = new Promise((resolve) => {
      this.resolveFinished = resolve;
    });
  }

  append(fragment: string): void {
    if (!fragment || this.finalized || this.settled) return;
    this.source += fragment;
    this.schedule(0);
  }

  finish(canonicalText = this.source): Promise<void> {
    if (this.settled) return this.finishedPromise;

    const displayed = this.source.slice(0, this.position);
    this.source = canonicalText;
    if (!canonicalText.startsWith(displayed)) {
      let sharedPrefix = 0;
      while (
        sharedPrefix < displayed.length &&
        canonicalText[sharedPrefix] === displayed[sharedPrefix]
      ) {
        sharedPrefix += 1;
      }
      this.position = sharedPrefix;
      this.onFrame(canonicalText.slice(0, sharedPrefix), canonicalText.length > sharedPrefix);
    }

    this.finalized = true;
    if (this.source.length === this.position) {
      this.settle();
    } else {
      this.schedule(0);
    }
    return this.finishedPromise;
  }

  cancel(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    this.settle();
  }

  private schedule(delay: number): void {
    if (this.timer !== null || this.settled) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.step();
    }, delay);
  }

  private step(): void {
    const end = nextUnitEnd(this.source, this.position, this.finalized);
    if (end === null) return;

    this.position = end;
    const active = !this.finalized || this.position < this.source.length;
    this.onFrame(this.source.slice(0, this.position), active);

    if (!active) {
      this.settle();
    } else if (this.position < this.source.length) {
      this.schedule(this.intervalMs);
    }
  }

  private settle(): void {
    if (this.settled) return;
    this.settled = true;
    this.resolveFinished?.();
    this.resolveFinished = null;
  }
}
