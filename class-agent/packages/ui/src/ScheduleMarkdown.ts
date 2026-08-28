import type { CalendarData, CalendarEvent, CalendarNotice } from "./Calendar.js";

type ScheduleColumn =
  | "week"
  | "date"
  | "weekDate"
  | "lecture"
  | "speakers"
  | "tutorial"
  | "readings";

interface MarkdownTable {
  columns: Map<ScheduleColumn, number>;
  rows: string[][];
  startLine: number;
}

interface SpeakerBlock {
  content: string;
  speakers?: string[];
}

function markdownTableRow(line: string): string[] | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("|")) return null;
  const body = trimmed.endsWith("|") ? trimmed.slice(1, -1) : trimmed.slice(1);
  const cells: string[] = [];
  let cell = "";
  for (let index = 0; index < body.length; index += 1) {
    const character = body[index];
    if (character === "\\" && index + 1 < body.length) {
      cell += character + body[index + 1];
      index += 1;
      continue;
    }
    if (character === "|") {
      cells.push(cell.trim());
      cell = "";
      continue;
    }
    cell += character;
  }
  cells.push(cell.trim());
  return cells;
}

function isTableSeparator(cells: string[]): boolean {
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function cleanInlineMarkdown(value: string): string {
  return value
    .replace(/<br\s*\/?\s*>/gi, " ")
    .replace(/\[([^\]]+)]\(([^)]+)\)/g, (_match, label: string, target: string) => {
      return `${label} (${target.trim()})`;
    })
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\\([\\`*{}[\]()#+\-.!_>|+])/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/_([^_]+)_/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function scheduleColumn(value: string): ScheduleColumn | null {
  const heading = cleanInlineMarkdown(value).toLocaleLowerCase();
  if (heading.includes("week") && heading.includes("date")) return "weekDate";
  if (heading.includes("week")) return "week";
  if (heading.includes("date")) return "date";
  if (heading.includes("lecture") || heading.includes("topic")) return "lecture";
  if (heading.includes("speaker") || heading.includes("instructor")) return "speakers";
  if (
    heading.includes("tutorial") ||
    heading.includes("hands-on") ||
    heading.includes("activity")
  ) {
    return "tutorial";
  }
  if (heading.includes("reading")) return "readings";
  return null;
}

function findScheduleTable(lines: string[]): MarkdownTable | null {
  for (let index = 0; index < lines.length - 1; index += 1) {
    const headingLine = lines[index];
    const separatorLine = lines[index + 1];
    if (headingLine === undefined || separatorLine === undefined) continue;
    const headings = markdownTableRow(headingLine);
    const separator = markdownTableRow(separatorLine);
    if (!headings || !separator || headings.length !== separator.length) continue;
    if (!isTableSeparator(separator)) continue;

    const columns = new Map<ScheduleColumn, number>();
    headings.forEach((heading, columnIndex) => {
      const column = scheduleColumn(heading);
      if (column && !columns.has(column)) columns.set(column, columnIndex);
    });
    const hasWeek = columns.has("weekDate") || columns.has("week");
    if (!hasWeek || !columns.has("lecture")) continue;

    const rows: string[][] = [];
    for (let rowIndex = index + 2; rowIndex < lines.length; rowIndex += 1) {
      const rowLine = lines[rowIndex];
      if (rowLine === undefined) break;
      const row = markdownTableRow(rowLine);
      if (!row) break;
      if (row.length === headings.length) rows.push(row);
    }
    return { columns, rows, startLine: index };
  }
  return null;
}

function columnValue(
  row: string[],
  columns: Map<ScheduleColumn, number>,
  column: ScheduleColumn,
): string {
  const index = columns.get(column);
  return index === undefined ? "" : (row[index] ?? "");
}

function parseWeek(value: string): { week: number; dateLabel?: string } | null {
  const normalized = cleanInlineMarkdown(value);
  const match = /^(?:week\s*)?(\d+)\b(.*)$/i.exec(normalized);
  if (!match) return null;
  const weekText = match[1];
  const trailingText = match[2];
  if (weekText === undefined || trailingText === undefined) return null;
  const week = Number(weekText);
  if (!Number.isSafeInteger(week) || week < 1) return null;
  const trailing = trailingText.trim();
  const dateLabel = trailing.replace(/^\((.*)\)$/, "$1").trim();
  if (!dateLabel || /^(?:—|-)$/.test(dateLabel)) return { week };
  return { week, dateLabel };
}

function splitSpeakers(value: string): string[] {
  return cleanInlineMarkdown(value)
    .split(/\s*(?:&|;|\band\b)\s*/i)
    .map((speaker) => speaker.trim())
    .filter(Boolean);
}

function withoutTrailingSpeakers(value: string): SpeakerBlock {
  const spans: Array<{ start: number; text: string }> = [];
  for (const match of value.matchAll(/(?<!\*)\*([^*\n]+)\*(?!\*)/g)) {
    const text = match[1];
    if (text === undefined) continue;
    const start = match.index ?? 0;
    spans.push({ start, text });
  }
  for (let index = 0; index < spans.length; index += 1) {
    const span = spans[index];
    if (!span) continue;
    const suffix = value.slice(span.start);
    const separators = suffix
      .replace(/\*[^*\n]+\*/g, "")
      .replace(/\band\b/gi, "")
      .replace(/[&,;./]/g, "")
      .trim();
    if (separators) continue;
    const speakers = spans.slice(index).flatMap((span) => splitSpeakers(span.text));
    return {
      content: value.slice(0, span.start).trim(),
      ...(speakers.length ? { speakers: [...new Set(speakers)] } : {}),
    };
  }
  return { content: value };
}

function parseLecture(value: string): Pick<
  CalendarEvent,
  "title" | "description" | "speakers"
> | null {
  const speakerBlock = withoutTrailingSpeakers(value);
  const boldTitle = /\*\*([^*]+)\*\*/.exec(speakerBlock.content);
  const title = cleanInlineMarkdown(boldTitle?.[1] ?? speakerBlock.content);
  if (!title) return null;
  const description = boldTitle
    ? cleanInlineMarkdown(
        speakerBlock.content.slice(0, boldTitle.index) +
          speakerBlock.content.slice(boldTitle.index + boldTitle[0].length),
      )
    : "";
  return {
    title,
    ...(description ? { description } : {}),
    ...(speakerBlock.speakers ? { speakers: speakerBlock.speakers } : {}),
  };
}

function supplementalText(value: string): string | undefined {
  const normalized = cleanInlineMarkdown(value);
  if (!normalized || /^(?:n\/?a|—|-|no class)$/i.test(normalized)) return undefined;
  return normalized;
}

function parseNotices(lines: string[]): CalendarNotice[] {
  const notices: CalendarNotice[] = [];
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!/^(?:\*\*|__)/.test(line)) continue;
    const normalized = cleanInlineMarkdown(line);
    if (!normalized) continue;
    const separator = normalized.indexOf(":");
    if (separator < 0) {
      notices.push({ label: normalized });
      continue;
    }
    const label = normalized.slice(0, separator).trim();
    const text = normalized.slice(separator + 1).trim();
    if (label) notices.push({ label, ...(text ? { text } : {}) });
  }
  return notices;
}

/** Parse the editable course Markdown into the trusted Calendar's normalized data. */
export function parseScheduleMarkdown(markdown: string): CalendarData {
  const lines = markdown.split(/\r?\n/);
  const table = findScheduleTable(lines);
  if (!table) return { events: [] };
  const notices = parseNotices(lines.slice(0, table.startLine));
  const events: CalendarEvent[] = [];

  for (const row of table.rows) {
    const weekSource = columnValue(
      row,
      table.columns,
      table.columns.has("weekDate") ? "weekDate" : "week",
    );
    const weekData = parseWeek(weekSource);
    const lecture = parseLecture(columnValue(row, table.columns, "lecture"));
    if (!weekData || !lecture) continue;

    const event: CalendarEvent = {
      id: `week-${weekData.week}`,
      week: weekData.week,
      type: lecture.title.toLocaleLowerCase() === "no class" ? "no-class" : "class",
      ...lecture,
    };
    const separateDate = supplementalText(columnValue(row, table.columns, "date"));
    const dateLabel = weekData.dateLabel ?? separateDate;
    if (dateLabel) event.dateLabel = dateLabel;

    const explicitSpeakers = splitSpeakers(columnValue(row, table.columns, "speakers"));
    if (explicitSpeakers.length) {
      event.speakers = [...new Set([...(event.speakers ?? []), ...explicitSpeakers])];
    }

    const tutorialBlock = withoutTrailingSpeakers(
      columnValue(row, table.columns, "tutorial"),
    );
    const activity = supplementalText(tutorialBlock.content);
    if (activity) event.activity = activity;
    if (tutorialBlock.speakers) event.tutorialSpeakers = tutorialBlock.speakers;

    const readings = supplementalText(columnValue(row, table.columns, "readings"));
    if (readings) event.readings = readings;
    events.push(event);
  }

  return {
    events,
    ...(notices.length ? { notices } : {}),
  };
}
