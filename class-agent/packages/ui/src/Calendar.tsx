import { useMemo, useState } from "react";

import { parseScheduleMarkdown } from "./ScheduleMarkdown.js";

export interface CalendarEvent {
  id: string;
  title: string;
  week?: number;
  start?: string;
  end?: string;
  type?: string;
  description?: string;
  dateLabel?: string;
  speakers?: string[];
  activity?: string;
  tutorialSpeakers?: string[];
  readings?: string;
}

export interface CalendarNotice {
  label: string;
  text?: string;
}

export interface CalendarData {
  events: CalendarEvent[];
  status?: string;
  notices?: CalendarNotice[];
  year?: number;
}

export interface CalendarProps {
  data: CalendarData;
  view?: "month" | "agenda" | undefined;
  focusDate?: string | undefined;
  selectedEventId?: string | undefined;
  onInteraction?: ((action: string, value: string) => void) | undefined;
}

type CalendarView = "month" | "agenda";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function textList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const values = value.flatMap((item) => {
    const normalized = text(item);
    return normalized ? [normalized] : [];
  });
  return values.length ? values : undefined;
}

function weekNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : undefined;
}

function calendarYear(value: unknown): number | undefined {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= 2000 &&
    value <= 2100
    ? value
    : undefined;
}

function normalizedEvent(value: unknown, index: number): CalendarEvent | null {
  if (!isRecord(value)) return null;
  const id = text(value.id) ?? `event-${index + 1}`;
  const title = text(value.title);
  if (!title) return null;
  const event: CalendarEvent = { id, title };
  const start = text(value.start);
  const end = text(value.end);
  const type = text(value.type);
  const description = text(value.description);
  const dateLabel = text(value.date_label) ?? text(value.dateLabel);
  const week = weekNumber(value.week);
  const speakers = textList(value.speakers);
  const activity = text(value.activity) ?? text(value.tutorial);
  const tutorialSpeakers =
    textList(value.tutorial_speakers) ?? textList(value.tutorialSpeakers);
  const readings = text(value.readings);
  if (week) event.week = week;
  if (start) event.start = start;
  if (end) event.end = end;
  if (type) event.type = type;
  if (description) event.description = description;
  if (dateLabel) event.dateLabel = dateLabel;
  if (speakers) event.speakers = speakers;
  if (activity) event.activity = activity;
  if (tutorialSpeakers) event.tutorialSpeakers = tutorialSpeakers;
  if (readings) event.readings = readings;
  return event;
}

export function normalizeCalendarData(value: unknown): CalendarData {
  if (typeof value === "string") return parseScheduleMarkdown(value);
  if (!isRecord(value)) return { events: [] };
  const status = text(value.status);
  const year = calendarYear(value.year);
  if (Array.isArray(value.events)) {
    const events = value.events
      .map((event, index) => normalizedEvent(event, index))
      .filter((event): event is CalendarEvent => event !== null);
    return { events, ...(status ? { status } : {}), ...(year ? { year } : {}) };
  }
  if (Array.isArray(value.weeks)) {
    const events = value.weeks.flatMap((week, index) => {
      if (!isRecord(week)) return [];
      const weekNumber =
        typeof week.week === "number" && Number.isFinite(week.week)
          ? week.week
          : index + 1;
      const title = text(week.lecture) ?? `Week ${weekNumber}`;
      const event: CalendarEvent = {
        id: `week-${weekNumber}`,
        title,
        week: weekNumber,
        type: "class",
      };
      const dateLabel = text(week.date_label);
      const speakers = textList(week.speakers);
      const activity = text(week.tutorial);
      const readings = text(week.readings);
      if (dateLabel) event.dateLabel = dateLabel;
      if (speakers) event.speakers = speakers;
      if (activity) event.activity = activity;
      if (readings) event.readings = readings;
      return [event];
    });
    return { events, ...(status ? { status } : {}), ...(year ? { year } : {}) };
  }
  return { events: [], ...(status ? { status } : {}), ...(year ? { year } : {}) };
}

function localDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(year, month - 1, day, 12);
  return Number.isNaN(date.getTime()) ? null : date;
}

function dateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dateLabelKey(value: string, year: number): string | null {
  const match = /^(\d{1,2})\/(\d{1,2})$/.exec(value.trim());
  if (!match) return null;
  const month = Number(match[1]);
  const day = Number(match[2]);
  const date = new Date(year, month - 1, day, 12);
  if (
    Number.isNaN(date.getTime()) ||
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }
  return dateKey(date);
}

function eventDateKey(event: CalendarEvent, scheduleYear: number): string | null {
  const date = event.start ? localDate(event.start) : null;
  if (date) return dateKey(date);
  return event.dateLabel ? dateLabelKey(event.dateLabel, scheduleYear) : null;
}

function formatEventDate(event: CalendarEvent): string {
  if (event.dateLabel) return event.dateLabel;
  if (!event.start) return "Date TBA";
  const date = new Date(event.start);
  if (Number.isNaN(date.getTime())) return event.start;
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: event.start.includes("T") ? "numeric" : undefined,
    minute: event.start.includes("T") ? "2-digit" : undefined,
  }).format(date);
}

function monthCells(focus: Date): Date[] {
  const first = new Date(focus.getFullYear(), focus.getMonth(), 1, 12);
  const start = new Date(first);
  start.setDate(first.getDate() - first.getDay());
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
}

export function Calendar({
  data,
  view = "agenda",
  focusDate,
  selectedEventId,
  onInteraction,
}: CalendarProps) {
  const [activeView, setActiveView] = useState<CalendarView>(view);
  const firstDatedEvent = data.events.find((event) => event.start)?.start;
  const rawRequestedFocus = focusDate ? localDate(focusDate) : null;
  const firstEventDate = firstDatedEvent ? localDate(firstDatedEvent) : null;
  const scheduleYear =
    data.year ??
    rawRequestedFocus?.getFullYear() ??
    firstEventDate?.getFullYear() ??
    new Date().getFullYear();
  const requestedFocus = rawRequestedFocus
    ? new Date(
        scheduleYear,
        rawRequestedFocus.getMonth(),
        rawRequestedFocus.getDate(),
        12,
      )
    : null;
  const firstLabeledEvent = data.events.find(
    (event) => event.dateLabel && dateLabelKey(event.dateLabel, scheduleYear),
  );
  const labeledFocus = firstLabeledEvent?.dateLabel
    ? localDate(dateLabelKey(firstLabeledEvent.dateLabel, scheduleYear) ?? "")
    : null;
  const initialFocus = requestedFocus || firstEventDate || labeledFocus || new Date();
  const [focus, setFocus] = useState(initialFocus);
  const [selectedId, setSelectedId] = useState(selectedEventId);
  const cells = useMemo(() => monthCells(focus), [focus]);

  function chooseEvent(event: CalendarEvent) {
    setSelectedId(event.id);
    onInteraction?.("select_event", event.id);
  }

  function changeView(next: CalendarView) {
    setActiveView(next);
    onInteraction?.("change_view", next);
  }

  return (
    <section aria-label="Course calendar" className="ca-calendar">
      <header className="ca-viewer-toolbar ca-calendar-toolbar">
        <div>
          <strong>Course schedule</strong>
        </div>
        <div aria-label="Calendar view" className="ca-calendar-view-switch" role="group">
          <button
            aria-pressed={activeView === "month"}
            onClick={() => changeView("month")}
            type="button"
          >
            Month
          </button>
          <button
            aria-pressed={activeView === "agenda"}
            onClick={() => changeView("agenda")}
            type="button"
          >
            Agenda
          </button>
        </div>
      </header>

      {data.notices?.length ? (
        <aside aria-label="Schedule notices" className="ca-calendar-notices">
          {data.notices.map((notice, index) => (
            <p key={`${notice.label}-${index}`}>
              <b>{notice.label}</b>
              {notice.text ? <span>{notice.text}</span> : null}
            </p>
          ))}
        </aside>
      ) : null}

      {activeView === "month" ? (
        <div className="ca-calendar-month">
          <div className="ca-calendar-month-navigation">
            <button
              aria-label="Previous month"
              onClick={() => setFocus(new Date(focus.getFullYear(), focus.getMonth() - 1, 1, 12))}
              type="button"
            >
              ←
            </button>
            <h2>
              {new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(
                focus,
              )}
            </h2>
            <button
              aria-label="Next month"
              onClick={() => setFocus(new Date(focus.getFullYear(), focus.getMonth() + 1, 1, 12))}
              type="button"
            >
              →
            </button>
          </div>
          <div aria-label="Month" className="ca-calendar-grid" role="grid">
            {Array.from({ length: 7 }, (_, day) => (
              <div className="ca-calendar-weekday" key={day} role="columnheader">
                {new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(
                  new Date(2026, 7, 23 + day, 12),
                )}
              </div>
            ))}
            {cells.map((date) => {
              const key = dateKey(date);
              const events = data.events.filter(
                (event) => eventDateKey(event, scheduleYear) === key,
              );
              return (
                <div
                  aria-label={new Intl.DateTimeFormat(undefined, {
                    weekday: "long",
                    month: "long",
                    day: "numeric",
                  }).format(date)}
                  className="ca-calendar-day"
                  data-outside-month={date.getMonth() !== focus.getMonth()}
                  key={key}
                  role="gridcell"
                >
                  <span>{date.getDate()}</span>
                  {events.map((event) => (
                    <button key={event.id} onClick={() => chooseEvent(event)} type="button">
                      {event.title}
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
          {data.events.some(
            (event) =>
              !event.start &&
              (!event.dateLabel || !dateLabelKey(event.dateLabel, scheduleYear)),
          ) ? (
            <p className="ca-calendar-undated-note">
              Events without confirmed dates are listed in Agenda view.
            </p>
          ) : null}
        </div>
      ) : (
        <ol className="ca-calendar-agenda">
          {data.events.map((event) => (
            <li data-selected={event.id === selectedId} key={event.id}>
              <button onClick={() => chooseEvent(event)} type="button">
                <span className="ca-calendar-agenda-meta">
                  {event.week ? <b>Week {event.week}</b> : null}
                  <time dateTime={event.start}>{formatEventDate(event)}</time>
                </span>
                <span className="ca-calendar-agenda-content">
                  <strong>{event.title}</strong>
                  {event.speakers?.length ? (
                    <span className="ca-calendar-agenda-speakers">
                      {event.speakers.length === 1 ? "Speaker" : "Speakers"}: {event.speakers.join(", ")}
                    </span>
                  ) : null}
                  {event.description ? (
                    <span className="ca-calendar-agenda-description">
                      {event.description}
                    </span>
                  ) : null}
                  {event.activity ? (
                    <span className="ca-calendar-agenda-activity">
                      <b>Hands-on tutorial</b>
                      <span>{event.activity}</span>
                      {event.tutorialSpeakers?.length ? (
                        <span className="ca-calendar-agenda-speakers">
                          {event.tutorialSpeakers.length === 1
                            ? "Tutorial lead"
                            : "Tutorial leads"}
                          : {event.tutorialSpeakers.join(", ")}
                        </span>
                      ) : null}
                    </span>
                  ) : null}
                  {event.readings ? (
                    <span className="ca-calendar-agenda-readings">
                      <b>Suggested readings</b>
                      <span>{event.readings}</span>
                    </span>
                  ) : null}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
