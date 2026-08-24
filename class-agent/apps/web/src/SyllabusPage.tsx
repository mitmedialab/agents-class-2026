import type { ReactNode } from "react";

interface MarkdownTable {
  headers: string[];
  rows: string[][];
}

function plainMarkdown(text: string): string {
  return text.replaceAll(/\\([\\`*{}\[\]()#+\-.!_>])/g, "$1");
}

function inlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
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
      return (
        <a href={link[2]} key={key} rel="noreferrer" target="_blank">
          {plainMarkdown(link[1])}
        </a>
      );
    }
    return plainMarkdown(part);
  });
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

function markdownBlocks(lines: string[], startIndex: number): ReactNode[] {
  const blocks: ReactNode[] = [];
  let index = startIndex;

  while (index < lines.length) {
    const line = lines[index]?.trim() ?? "";
    if (!line) {
      index += 1;
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading?.[2]) {
      const level = heading[1]?.length ?? 2;
      const content = inlineMarkdown(heading[2], `heading-${index}`);
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
                    {inlineMarkdown(header, `header-${index}-${cellIndex}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`cell-${cellIndex}`}>
                      {inlineMarkdown(cell, `cell-${rowIndex}-${cellIndex}`)}
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
            {inlineMarkdown(item[1], `bullet-${index}`)}
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
            {inlineMarkdown(item[1], `number-${index}`)}
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
        (candidate.includes("|") && isTableDivider(lines[index + 1] ?? ""))
      ) {
        break;
      }
      paragraph.push(candidate);
      index += 1;
    }
    blocks.push(
      <p key={`paragraph-${index}`}>
        {inlineMarkdown(paragraph.join(" "), `paragraph-${index}`)}
      </p>,
    );
  }

  return blocks;
}

export interface SyllabusPageProps {
  content: string | null;
  error: string | null;
  loading: boolean;
}

export function SyllabusPage({ content, error, loading }: SyllabusPageProps) {
  if (loading) {
    return (
      <main className="syllabus-page">
        <p className="syllabus-status">Loading syllabus…</p>
      </main>
    );
  }
  if (error || content === null) {
    return (
      <main className="syllabus-page">
        <p className="syllabus-status" role="alert">
          {error ?? "The syllabus is unavailable."}
        </p>
      </main>
    );
  }

  const lines = content.split("\n");
  const titleIndex = lines.findIndex((line) => /^#\s+/.test(line.trim()));
  const title =
    titleIndex >= 0 ? lines[titleIndex]?.trim().replace(/^#\s+/, "") ?? "Syllabus" : "Syllabus";
  const metadata: Array<{ label: string; value: string }> = [];
  let bodyStart = Math.max(titleIndex + 1, 0);
  while (bodyStart < lines.length) {
    const line = lines[bodyStart]?.trim() ?? "";
    if (!line) {
      bodyStart += 1;
      continue;
    }
    const field = /^\*\*([^*]+?):\*\*\s*(.+)$/.exec(line);
    if (!field?.[1] || !field[2]) break;
    metadata.push({ label: field[1], value: field[2] });
    bodyStart += 1;
  }

  return (
    <main className="syllabus-page">
      <article className="syllabus-document">
        <h1>{inlineMarkdown(title, "title")}</h1>
        {metadata.length ? (
          <dl className="syllabus-metadata">
            {metadata.map((field) => (
              <div key={field.label}>
                <dt>{field.label}</dt>
                <dd>{inlineMarkdown(field.value, `metadata-${field.label}`)}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        <div className="syllabus-sections">{markdownBlocks(lines, bodyStart)}</div>
      </article>
    </main>
  );
}
