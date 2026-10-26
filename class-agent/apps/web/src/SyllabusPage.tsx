import { PdfDownload } from "@class-agent/ui";
import { Fragment, type ReactNode } from "react";

interface MarkdownTable {
  headers: string[];
  rows: string[][];
}

/** Links and images resolve through the page that owns the document, never on their own. */
export interface DocumentLinkContext {
  /** The in-app path for a `course://` link whose resource has a page, if any. */
  courseLinkPath?: ((uri: string) => string | null) | undefined;
  /** Opens that page in place of a full navigation. */
  onCourseLink?: ((uri: string) => void) | undefined;
  /** Where an image loads from: a registered asset id or an https URL; null drops it. */
  resolveImageSource?: ((source: string) => string | null) | undefined;
}

const IMAGE_BLOCK = /^(?:\[)?!\[([^\]]*)\]\(([^)\s]+)\)(?:\]\(([^)\s]+)\))?$/;
// A labelled line: the form of the facts under a page title, also honored inside the body.
const FACT_LINE = /^\*\*([^*]+?):\*\*\s*(.+)$/;
const RULE_LINE = /^(?:-{3,}|\*{3,}|_{3,})$/;

function plainMarkdown(text: string): string {
  return text.replaceAll(/\\([\\`*{}\[\]()#+\-.!_<>|~])/g, "$1");
}

function linkElement(
  href: string,
  label: ReactNode,
  key: string,
  context: DocumentLinkContext,
): ReactNode {
  if (href.startsWith("course://")) {
    const path = context.courseLinkPath?.(href) ?? null;
    if (path === null) return label;
    return (
      <a
        href={path}
        key={key}
        onClick={(event) => {
          event.preventDefault();
          context.onCourseLink?.(href);
        }}
      >
        {label}
      </a>
    );
  }
  return (
    <a href={href} key={key} rel="noreferrer" target="_blank">
      {label}
    </a>
  );
}

function inlineMarkdown(
  text: string,
  keyPrefix: string,
  context: DocumentLinkContext = {},
): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g);
  return parts.filter(Boolean).map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key}>{plainMarkdown(part.slice(2, -2))}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={key}>{plainMarkdown(part.slice(1, -1))}</em>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    const link = /^\[([^\]]+)]\(([^)]+)\)$/.exec(part);
    if (link?.[1] && link[2]) {
      return linkElement(link[2], plainMarkdown(link[1]), key, context);
    }
    return plainMarkdown(part);
  });
}

/** A line that is only an image, optionally wrapped in a link, becomes a figure. */
function figureBlock(
  line: string,
  key: string,
  context: DocumentLinkContext,
): ReactNode | null {
  const image = IMAGE_BLOCK.exec(line);
  if (!image?.[2]) return null;
  const source = context.resolveImageSource?.(image[2]) ?? null;
  if (source === null) return <Fragment key={key} />;
  const picture = <img alt={plainMarkdown(image[1] ?? "")} src={source} />;
  return (
    <figure className="syllabus-figure" key={key}>
      {image[3] ? linkElement(image[3], picture, `${key}-link`, context) : picture}
    </figure>
  );
}

function tableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableDivider(line: string): boolean {
  const cells = tableCells(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function markdownBlocks(
  lines: string[],
  startIndex: number,
  context: DocumentLinkContext = {},
): ReactNode[] {
  const blocks: ReactNode[] = [];
  let index = startIndex;

  while (index < lines.length) {
    const line = lines[index]?.trim() ?? "";
    if (!line) {
      index += 1;
      continue;
    }

    const figure = figureBlock(line, `figure-${index}`, context);
    if (figure !== null) {
      blocks.push(figure);
      index += 1;
      continue;
    }

    if (RULE_LINE.test(line)) {
      blocks.push(<hr key={`rule-${index}`} />);
      index += 1;
      continue;
    }

    if (FACT_LINE.test(line)) {
      const facts: Array<{ label: string; value: string }> = [];
      while (index < lines.length) {
        const fact = FACT_LINE.exec(lines[index]?.trim() ?? "");
        if (!fact?.[1] || !fact[2]) break;
        facts.push({ label: fact[1], value: fact[2] });
        index += 1;
      }
      blocks.push(
        <dl className="syllabus-facts" key={`facts-${index}`}>
          {facts.map((fact, factIndex) => (
            <div key={`fact-${index}-${factIndex}`}>
              <dt>{inlineMarkdown(fact.label, `fact-label-${index}-${factIndex}`, context)}</dt>
              <dd>{inlineMarkdown(fact.value, `fact-${index}-${factIndex}`, context)}</dd>
            </div>
          ))}
        </dl>,
      );
      continue;
    }

    if (line.startsWith(">")) {
      const quoted: string[] = [];
      while (index < lines.length && (lines[index]?.trim() ?? "").startsWith(">")) {
        quoted.push((lines[index]?.trim() ?? "").replace(/^>\s?/, ""));
        index += 1;
      }
      const paragraphs = quoted
        .join("\n")
        .split(/\n\s*\n/)
        .map((paragraph) => paragraph.replaceAll("\n", " ").trim())
        .filter(Boolean);
      blocks.push(
        <blockquote key={`quote-${index}`}>
          {paragraphs.map((paragraph, paragraphIndex) => (
            <p key={`quote-${index}-${paragraphIndex}`}>
              {inlineMarkdown(paragraph, `quote-${index}-${paragraphIndex}`, context)}
            </p>
          ))}
        </blockquote>,
      );
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading?.[2]) {
      const level = heading[1]?.length ?? 2;
      const content = inlineMarkdown(heading[2], `heading-${index}`, context);
      blocks.push(
        level === 1 ? (
          <h1 key={`heading-${index}`}>{content}</h1>
        ) : level === 2 ? (
          <h2 key={`heading-${index}`}>{content}</h2>
        ) : (
          <h3 key={`heading-${index}`}>{content}</h3>
        ),
      );
      index += 1;
      continue;
    }

    if (line.includes("|") && isTableDivider(lines[index + 1] ?? "")) {
      const table: MarkdownTable = { headers: tableCells(line), rows: [] };
      index += 2;
      while (index < lines.length && (lines[index] ?? "").includes("|")) {
        table.rows.push(tableCells(lines[index] ?? ""));
        index += 1;
      }
      blocks.push(
        <div className="syllabus-table-scroll" key={`table-${index}`}>
          <table>
            <thead>
              <tr>
                {table.headers.map((header, cellIndex) => (
                  <th key={`header-${cellIndex}`}>
                    {inlineMarkdown(header, `header-${index}-${cellIndex}`, context)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`cell-${cellIndex}`}>
                      {inlineMarkdown(cell, `cell-${rowIndex}-${cellIndex}`, context)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const item = /^[-*]\s+(.+)$/.exec(lines[index]?.trim() ?? "");
        if (!item?.[1]) break;
        items.push(
          <li key={`bullet-${index}`}>
            {inlineMarkdown(item[1], `bullet-${index}`, context)}
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
            {inlineMarkdown(item[1], `number-${index}`, context)}
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
        /^\d+[.)]\s+/.test(candidate) ||
        candidate.startsWith(">") ||
        IMAGE_BLOCK.test(candidate) ||
        FACT_LINE.test(candidate) ||
        RULE_LINE.test(candidate) ||
        (candidate.includes("|") && isTableDivider(lines[index + 1] ?? ""))
      ) {
        break;
      }
      paragraph.push(candidate);
      index += 1;
    }
    blocks.push(
      <p key={`paragraph-${index}`}>
        {inlineMarkdown(paragraph.join(" "), `paragraph-${index}`, context)}
      </p>,
    );
  }

  return blocks;
}

/** A reference document keeps the wide column its tables need; reading prose gets a measure. */
export type DocumentLayout = "reference" | "reading";

export interface SyllabusPageProps extends DocumentLinkContext {
  layout?: DocumentLayout;
  pdfDownloadUrl?: string | undefined;
  pdfLabel?: string;
  pdfTitle?: string;
  content: string | null;
  error: string | null;
  loading: boolean;
  loadingMessage?: string;
}

/** Renders a course Markdown document: the syllabus, a newsletter issue, or another page. */
export function SyllabusPage({
  content,
  courseLinkPath,
  error,
  layout = "reference",
  loading,
  loadingMessage = "Loading syllabus…",
  onCourseLink,
  pdfDownloadUrl,
  pdfLabel = "Download syllabus PDF",
  pdfTitle = "Course syllabus",
  resolveImageSource,
}: SyllabusPageProps) {
  const context: DocumentLinkContext = { courseLinkPath, onCourseLink, resolveImageSource };
  if (loading) {
    return (
      <main className="syllabus-page">
        <p className="syllabus-status">{loadingMessage}</p>
      </main>
    );
  }
  if (error || content === null) {
    return (
      <main className="syllabus-page">
        <p className="syllabus-status" role="alert">
          {error ?? "This page is unavailable."}
        </p>
      </main>
    );
  }

  const lines = content.split("\n");
  const titleIndex = lines.findIndex((line) => /^#\s+/.test(line.trim()));
  const title =
    titleIndex >= 0 ? lines[titleIndex]?.trim().replace(/^#\s+/, "") ?? "Syllabus" : "Syllabus";
  const mastheadLine = lines
    .slice(0, Math.max(titleIndex, 0))
    .map((line) => line.trim())
    .find((line) => IMAGE_BLOCK.test(line));
  const masthead = mastheadLine ? figureBlock(mastheadLine, "masthead", context) : null;
  const mastheadAlt = mastheadLine ? plainMarkdown(IMAGE_BLOCK.exec(mastheadLine)?.[1] ?? "") : "";
  const titleShownByMasthead =
    masthead !== null && mastheadAlt.length > 0 && mastheadAlt === plainMarkdown(title);
  const metadata: Array<{ label: string; value: string }> = [];
  let bodyStart = Math.max(titleIndex + 1, 0);
  while (bodyStart < lines.length) {
    const line = lines[bodyStart]?.trim() ?? "";
    if (!line) {
      bodyStart += 1;
      continue;
    }
    const field = FACT_LINE.exec(line);
    if (!field?.[1] || !field[2]) break;
    metadata.push({ label: field[1], value: field[2] });
    bodyStart += 1;
  }

  return (
    <main className="syllabus-page">
      <article className="syllabus-document" data-layout={layout}>
        {pdfDownloadUrl ? (
          <div className="syllabus-download">
            <PdfDownload href={pdfDownloadUrl} title={pdfTitle} label={pdfLabel} />
          </div>
        ) : null}
        {masthead ? <div className="syllabus-masthead">{masthead}</div> : null}
        <h1 className={titleShownByMasthead ? "ca-visually-hidden" : undefined}>
          {inlineMarkdown(title, "title", context)}
        </h1>
        {metadata.length ? (
          <dl className="syllabus-metadata">
            {metadata.map((field) => (
              <div key={field.label}>
                <dt>{inlineMarkdown(field.label, `metadata-label-${field.label}`, context)}</dt>
                <dd>{inlineMarkdown(field.value, `metadata-${field.label}`, context)}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        <div className="syllabus-sections">{markdownBlocks(lines, bodyStart, context)}</div>
      </article>
    </main>
  );
}
