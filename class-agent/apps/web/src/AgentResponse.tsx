import type { CSSProperties, ReactNode } from "react";

const MIN_CONTENT_LOAD = 40;
const MAX_CONTENT_LOAD = 900;

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

function responseStyle(text: string): CSSProperties {
  const scale = responseScale(text);
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

function characterNodes(text: string, keyPrefix: string, streaming: boolean): ReactNode {
  if (!streaming) return text;
  return Array.from(text).map((character, index) => (
    <span className="response-character" key={`${keyPrefix}-character-${index}`}>
      {character}
    </span>
  ));
}

function inlineMarkup(text: string, keyPrefix: string, streaming: boolean): ReactNode[] {
  return text.split(/(\*\*[^*\n]+\*\*)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={`${keyPrefix}-strong-${index}`}>
          {characterNodes(part.slice(2, -2), `${keyPrefix}-strong-${index}`, streaming)}
        </strong>
      );
    }
    return characterNodes(part, `${keyPrefix}-plain-${index}`, streaming);
  });
}

function responseBlocks(text: string, streaming: boolean): ReactNode[] {
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
          {inlineMarkup(heading[2], `h-${index}`, streaming)}
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
            {inlineMarkup(item[1], `b-${index}`, streaming)}
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
            {inlineMarkup(item[1], `n-${index}`, streaming)}
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
        {inlineMarkup(paragraphText, `p-${index}`, streaming)}
      </p>,
    );
  }

  return blocks;
}

export interface AgentResponseProps {
  streaming?: boolean;
  text: string;
}

export function AgentResponse({ streaming = false, text }: AgentResponseProps) {
  const scale = responseScale(text);
  return (
    <div
      className="latest-response"
      data-response-scale={scale.toFixed(3)}
      data-streaming={streaming}
      style={responseStyle(text)}
    >
      {responseBlocks(text, streaming)}
    </div>
  );
}
