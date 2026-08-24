import type { ReactNode } from "react";

export type ResponseDensity = "short" | "medium" | "long";

export function responseDensity(text: string): ResponseDensity {
  const visibleLines = text.split("\n").filter((line) => line.trim()).length;
  if (text.length <= 180 && visibleLines <= 3) return "short";
  if (text.length <= 520 && visibleLines <= 10) return "medium";
  return "long";
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
  return (
    <div
      className="latest-response"
      data-density={responseDensity(text)}
      data-streaming={streaming}
    >
      {responseBlocks(text, streaming)}
    </div>
  );
}
