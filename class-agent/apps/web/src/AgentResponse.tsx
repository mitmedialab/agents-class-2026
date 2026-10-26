import {
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { linkFaviconUrl } from "./api.js";

const MIN_CONTENT_LOAD = 40;
const MAX_CONTENT_LOAD = 900;
const RESPONSE_FIT_ITERATIONS = 9;
const RESPONSE_FIT_TOLERANCE_PX = 1;
export const RESPONSE_CHARACTER_STAGGER_MS = 14;
const INLINE_MARKUP_PATTERN = /(\[[^\]\n]+\]\([^\s)]+\)|\*\*[^*\n]+\*\*|\*[^*\n]+\*)/g;

function safeResponseHref(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export function responseScale(text: string): number {
  const visibleLines = text.split("\n").filter((line) => line.trim()).length;
  const contentLoad = text.length + Math.max(0, visibleLines - 1) * 36;
  const progress = Math.min(
    1,
    Math.max(0, (contentLoad - MIN_CONTENT_LOAD) / (MAX_CONTENT_LOAD - MIN_CONTENT_LOAD)),
  );
  const easedProgress = progress * progress * (3 - 2 * progress);
  return 1 - easedProgress;
}

function interpolate(small: number, large: number, scale: number): number {
  return small + (large - small) * scale;
}

function responseStyle(scale: number): CSSProperties {
  return {
    "--response-font-min": `${interpolate(1.05, 1.75, scale).toFixed(3)}rem`,
    "--response-font-fluid": `${interpolate(1.55, 3.5, scale).toFixed(3)}vw`,
    "--response-font-max": `${interpolate(1.5, 3.875, scale).toFixed(3)}rem`,
    "--response-mobile-min": `${interpolate(1, 1.5, scale).toFixed(3)}rem`,
    "--response-mobile-fluid": `${interpolate(4.2, 8, scale).toFixed(3)}vw`,
    "--response-mobile-max": `${interpolate(1, 2.25, scale).toFixed(3)}rem`,
    "--response-letter-spacing": `${interpolate(-0.01, -0.035, scale).toFixed(4)}em`,
    "--response-line-height": interpolate(1.48, 1.12, scale).toFixed(3),
    "--response-max-width": `${interpolate(52, 24, scale).toFixed(2)}ch`,
    "--response-padding-inline": `${interpolate(1.5, 0.25, scale).toFixed(3)}rem`,
    "--response-padding-bottom": `${interpolate(2, 0.25, scale).toFixed(3)}rem`,
  } as CSSProperties;
}

interface ResponseFit {
  expanded: boolean;
  fits: boolean | null;
  measured: boolean;
  scale: number;
  text: string;
}

function applyResponseScale(element: HTMLElement, scale: number): void {
  for (const [property, value] of Object.entries(responseStyle(scale))) {
    element.style.setProperty(property, String(value));
  }
}

function fitResponseElement(
  element: HTMLElement,
  preferredScale?: number,
): Pick<ResponseFit, "expanded" | "fits" | "scale"> | null {
  const stage = element.parentElement;
  if (!stage) return null;
  const previousStyle = element.getAttribute("style");
  const previousMeasuringState = element.getAttribute("data-response-measuring");
  element.style.transition = "none";

  try {
    const fittingScale = (layout: "standard" | "expanded"): number | null => {
      element.dataset.responseMeasuring = layout;
      const fitsAtScale = (scale: number): boolean => {
        applyResponseScale(element, scale);
        return stage.scrollHeight <= stage.clientHeight + RESPONSE_FIT_TOLERANCE_PX;
      };

      if (stage.clientHeight <= 0) return null;
      if (preferredScale !== undefined) {
        return fitsAtScale(preferredScale) ? preferredScale : null;
      }
      if (fitsAtScale(1)) return 1;
      if (!fitsAtScale(0)) return null;

      let fitting = 0;
      let overflowing = 1;
      for (let index = 0; index < RESPONSE_FIT_ITERATIONS; index += 1) {
        const candidate = (fitting + overflowing) / 2;
        if (fitsAtScale(candidate)) {
          fitting = candidate;
        } else {
          overflowing = candidate;
        }
      }
      return fitting;
    };

    element.dataset.responseMeasuring = "standard";
    if (stage.clientHeight <= 0) return null;
    const standardScale = fittingScale("standard");
    if (standardScale !== null) {
      return { expanded: false, fits: true, scale: standardScale };
    }

    const expandedScale = fittingScale("expanded");
    return expandedScale === null
      ? { expanded: true, fits: false, scale: preferredScale ?? 0 }
      : { expanded: true, fits: true, scale: expandedScale };
  } finally {
    if (previousMeasuringState === null) {
      delete element.dataset.responseMeasuring;
    } else {
      element.dataset.responseMeasuring = previousMeasuringState;
    }
    if (previousStyle === null) {
      element.removeAttribute("style");
    } else {
      element.setAttribute("style", previousStyle);
    }
  }
}

function characterNodes(
  text: string,
  keyPrefix: string,
  _streaming: boolean,
  staggerCharacters: boolean,
  initialCharacterDelayMs: number,
): ReactNode {
  if (!staggerCharacters) return text;
  const characterCount = Array.from(text).length;
  let characterIndex = 0;

  return text
    .split(/(\s+)/g)
    .filter(Boolean)
    .map((token, tokenIndex) => {
      const tokenCharacters = Array.from(token).map((character) => {
        const index = characterIndex;
        characterIndex += 1;
        const delay = initialCharacterDelayMs + index * RESPONSE_CHARACTER_STAGGER_MS;
        const className =
          index === characterCount - 1
            ? "response-character response-character-last"
            : "response-character";
        return (
          <span
            className={className}
            key={`${keyPrefix}-character-${index}`}
            style={
              staggerCharacters
                ? ({
                    "--response-character-delay": `${delay}ms`,
                    animationDelay: `${delay}ms`,
                  } as CSSProperties)
                : undefined
            }
          >
            {character}
          </span>
        );
      });

      return /^\s+$/.test(token) ? (
        tokenCharacters
      ) : (
        <span className="response-word" key={`${keyPrefix}-word-${tokenIndex}`}>
          {tokenCharacters}
        </span>
      );
    });
}

function inlineMarkup(
  text: string,
  keyPrefix: string,
  streaming: boolean,
  staggerCharacters: boolean,
  initialCharacterDelayMs: number,
): ReactNode[] {
  return text.split(INLINE_MARKUP_PATTERN).map((part, index) => {
    const link = /^\[([^\]\n]+)]\(([^\s)]+)\)$/.exec(part);
    if (link?.[1] && link[2]) {
      const href = safeResponseHref(link[2]);
      if (href) {
        return (
          <a
            href={href}
            key={`${keyPrefix}-link-${index}`}
            rel="noreferrer"
            target="_blank"
          >
            <img
              alt=""
              aria-hidden="true"
              className="response-link-favicon"
              loading="lazy"
              onError={(event) => {
                event.currentTarget.hidden = true;
              }}
              src={linkFaviconUrl(href)}
            />
            {characterNodes(
              link[1],
              `${keyPrefix}-link-${index}`,
              streaming,
              staggerCharacters,
              initialCharacterDelayMs,
            )}
          </a>
        );
      }
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={`${keyPrefix}-strong-${index}`}>
          {characterNodes(
            part.slice(2, -2),
            `${keyPrefix}-strong-${index}`,
            streaming,
            staggerCharacters,
            initialCharacterDelayMs,
          )}
        </strong>
      );
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return (
        <em key={`${keyPrefix}-emphasis-${index}`}>
          {characterNodes(
            part.slice(1, -1),
            `${keyPrefix}-emphasis-${index}`,
            streaming,
            staggerCharacters,
            initialCharacterDelayMs,
          )}
        </em>
      );
    }
    return characterNodes(
      part,
      `${keyPrefix}-plain-${index}`,
      streaming,
      staggerCharacters,
      initialCharacterDelayMs,
    );
  });
}

function responseBlocks(
  text: string,
  streaming: boolean,
  staggerCharacters: boolean,
  initialCharacterDelayMs: number,
): ReactNode[] {
  const lines = text.trim().split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index]?.trim() ?? "";
    if (!line) {
      index += 1;
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading?.[2]) {
      blocks.push(
        <h2 key={`heading-${index}`}>
          {inlineMarkup(
            heading[2],
            `h-${index}`,
            streaming,
            staggerCharacters,
            initialCharacterDelayMs,
          )}
        </h2>,
      );
      index += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const item = /^[-*]\s+(.+)$/.exec(lines[index]?.trim() ?? "");
        if (!item?.[1]) break;
        items.push(
          <li key={`bullet-${index}`}>
            {inlineMarkup(
              item[1],
              `b-${index}`,
              streaming,
              staggerCharacters,
              initialCharacterDelayMs,
            )}
          </li>,
        );
        index += 1;
      }
      blocks.push(<ul key={`bullets-${index}`}>{items}</ul>);
      continue;
    }

    if (/^\d+[.)]\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const item = /^\d+[.)]\s+(.+)$/.exec(lines[index]?.trim() ?? "");
        if (!item?.[1]) break;
        items.push(
          <li key={`number-${index}`}>
            {inlineMarkup(
              item[1],
              `n-${index}`,
              streaming,
              staggerCharacters,
              initialCharacterDelayMs,
            )}
          </li>,
        );
        index += 1;
      }
      blocks.push(<ol key={`numbers-${index}`}>{items}</ol>);
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length) {
      const candidate = lines[index]?.trim() ?? "";
      if (
        !candidate ||
        /^#{1,3}\s+/.test(candidate) ||
        /^[-*]\s+/.test(candidate) ||
        /^\d+[.)]\s+/.test(candidate)
      ) {
        break;
      }
      paragraph.push(candidate);
      index += 1;
    }
    const paragraphText = paragraph.join(" ");
    blocks.push(
      <p key={`paragraph-${index}`}>
        {inlineMarkup(
          paragraphText,
          `p-${index}`,
          streaming,
          staggerCharacters,
          initialCharacterDelayMs,
        )}
      </p>,
    );
  }

  return blocks;
}

export interface AgentResponseProps {
  initialCharacterDelayMs?: number;
  staggerCharacters?: boolean;
  stableScroll?: boolean;
  streaming?: boolean;
  text: string;
}

export function AgentResponse({
  initialCharacterDelayMs = 0,
  staggerCharacters = false,
  stableScroll = false,
  streaming = false,
  text,
}: AgentResponseProps) {
  const responseRef = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState<ResponseFit>(() => ({
    expanded: false,
    fits: null,
    measured: false,
    scale: responseScale(text),
    text,
  }));
  const currentFit = stableScroll
    ? {
        expanded: true,
        fits: false,
        measured: true,
        scale: 0,
        text,
      }
    : fit.text === text
      ? fit
      : {
          expanded: false,
          fits: null,
          measured: false,
          scale: responseScale(text),
          text,
        };

  useLayoutEffect(() => {
    if (stableScroll) return;
    const element = responseRef.current;
    const stage = element?.parentElement;
    if (!element || !stage) return;
    let animationFrame = 0;

    const measure = () => {
      const result = fitResponseElement(
        element,
        streaming ? responseScale(text) : undefined,
      );
      if (!result) return;
      setFit((existing) => {
        if (
          existing.text === text &&
          existing.measured &&
          existing.expanded === result.expanded &&
          existing.fits === result.fits &&
          Math.abs(existing.scale - result.scale) < 0.001
        ) {
          return existing;
        }
        return { ...result, measured: true, text };
      });
    };
    const scheduleMeasure = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(measure);
    };

    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(scheduleMeasure);
    // The response layout itself compacts the header when scrolling is needed.
    // Observing that header would turn each temporary fit measurement into a
    // new resize notification and continuously restart the measurement.
    observer?.observe(stage);
    const mutationObserver =
      typeof MutationObserver === "undefined"
        ? null
        : new MutationObserver(() => {
            scheduleMeasure();
          });
    mutationObserver?.observe(stage, { childList: true });
    window.addEventListener("resize", scheduleMeasure);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      window.removeEventListener("resize", scheduleMeasure);
      mutationObserver?.disconnect();
      observer?.disconnect();
    };
  }, [stableScroll, streaming, text]);

  return (
    <div
      ref={responseRef}
      className="latest-response"
      data-character-delay={initialCharacterDelayMs}
      data-response-fit={currentFit.measured ? "measured" : "estimated"}
      data-response-layout={currentFit.expanded ? "expanded" : "standard"}
      data-response-overflow={currentFit.fits === false}
      data-response-scale={currentFit.scale.toFixed(3)}
      data-response-stable-scroll={stableScroll}
      data-staggered={staggerCharacters}
      data-streaming={streaming}
      style={responseStyle(currentFit.scale)}
    >
      {responseBlocks(
        text,
        streaming,
        staggerCharacters,
        initialCharacterDelayMs,
      )}
    </div>
  );
}
