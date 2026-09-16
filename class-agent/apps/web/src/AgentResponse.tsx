import {
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

const MIN_CONTENT_LOAD = 40;
const MAX_CONTENT_LOAD = 900;
const RESPONSE_FIT_ITERATIONS = 9;
const RESPONSE_FIT_TOLERANCE_PX = 1;
export const RESPONSE_CHARACTER_STAGGER_MS = 14;

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
): Pick<ResponseFit, "fits" | "scale"> | null {
  const previousStyle = element.getAttribute("style");
  element.style.transition = "none";

  try {
    const fitsAtScale = (scale: number): boolean => {
      applyResponseScale(element, scale);
      return element.scrollHeight <= element.clientHeight + RESPONSE_FIT_TOLERANCE_PX;
    };

    applyResponseScale(element, 1);
    if (element.clientHeight <= 0) return null;
    if (fitsAtScale(1)) return { fits: true, scale: 1 };
    if (!fitsAtScale(0)) return { fits: false, scale: 0 };

    let fittingScale = 0;
    let overflowingScale = 1;
    for (let index = 0; index < RESPONSE_FIT_ITERATIONS; index += 1) {
      const candidate = (fittingScale + overflowingScale) / 2;
      if (fitsAtScale(candidate)) {
        fittingScale = candidate;
      } else {
        overflowingScale = candidate;
      }
    }
    return { fits: true, scale: fittingScale };
  } finally {
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
  streaming: boolean,
  staggerCharacters: boolean,
  initialCharacterDelayMs: number,
): ReactNode {
  if (!streaming && !staggerCharacters) return text;
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
  return text.split(/(\*\*[^*\n]+\*\*)/g).map((part, index) => {
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
  streaming?: boolean;
  text: string;
}

export function AgentResponse({
  initialCharacterDelayMs = 0,
  staggerCharacters = false,
  streaming = false,
  text,
}: AgentResponseProps) {
  const responseRef = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState<ResponseFit>(() => ({
    fits: null,
    measured: false,
    scale: responseScale(text),
    text,
  }));
  const currentFit =
    fit.text === text
      ? fit
      : { fits: null, measured: false, scale: responseScale(text), text };

  useLayoutEffect(() => {
    const element = responseRef.current;
    if (!element) return;
    let animationFrame = 0;

    const measure = () => {
      const result = fitResponseElement(element);
      if (!result) return;
      setFit((existing) => {
        if (
          existing.text === text &&
          existing.measured &&
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
    if (element.parentElement) observer?.observe(element.parentElement);
    window.addEventListener("resize", scheduleMeasure);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      window.removeEventListener("resize", scheduleMeasure);
      observer?.disconnect();
    };
  }, [text]);

  return (
    <div
      ref={responseRef}
      className="latest-response"
      data-character-delay={initialCharacterDelayMs}
      data-response-fit={currentFit.measured ? "measured" : "estimated"}
      data-response-overflow={currentFit.fits === false}
      data-response-scale={currentFit.scale.toFixed(3)}
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
