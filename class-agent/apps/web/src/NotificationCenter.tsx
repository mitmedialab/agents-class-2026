import { Button } from "@class-agent/ui";
import { useMemo, useState, type ReactNode, type UIEvent } from "react";

import type {
  NotificationCenterData,
  NotificationCenterItem,
  NotificationCenterSection,
} from "./api.js";
import { courseResourceAssetUrl } from "./api.js";

const SECTIONS: ReadonlyArray<{
  id: NotificationCenterSection;
  label: string;
}> = [
  { id: "notifications", label: "Updates" },
  { id: "communications", label: "Communications" },
  { id: "upcoming", label: "Upcoming" },
];

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const HISTORY_PREVIEW_COUNT = 3;
const RELATIVE_TIME_FORMATTER = new Intl.RelativeTimeFormat(undefined, {
  numeric: "auto",
  style: "short",
});

const STATE_LABELS: Record<NotificationCenterItem["state"], string> = {
  past: "Past",
  pending: "Pending",
  read: "Viewed",
  responded: "Staff replied",
  unread: "New",
  upcoming: "Upcoming",
};

interface NotificationCenterProps {
  busy: boolean;
  data: NotificationCenterData;
  historyExpanded: boolean;
  onAction: (item: NotificationCenterItem) => void;
  onHistoryExpandedChange: (expanded: boolean) => void;
  onMarkRead: (itemId: string) => void;
}

function CloseIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="9.25" />
      <path d="m9 9 6 6m0-6-6 6" />
    </svg>
  );
}

function NotificationKindIcon({ kind }: { kind: NotificationCenterItem["kind"] }) {
  let drawing: ReactNode;
  switch (kind) {
    case "course_update":
      drawing = (
        <>
          <path d="M7.5 3.75h6l3 3v13.5h-9z" />
          <path d="M13.5 3.75v3h3M10 11h4M10 14.5h4" />
        </>
      );
      break;
    case "pending_message":
    case "instructor_message":
      drawing = (
        <>
          <path d="M4.25 5.75h15.5v10.5H9l-4.75 3z" />
          <path d="M8 9.5h8M8 12.5h5" />
        </>
      );
      break;
    case "staff_reply":
      drawing = (
        <>
          <path d="M4.25 5.75h15.5v10.5H9l-4.75 3z" />
          <path d="m9 11.25 2 2 4-4" />
        </>
      );
      break;
    case "pending_student_question":
      drawing = (
        <>
          <path d="M4.25 5.75h15.5v10.5H9l-4.75 3z" />
          <path d="M10 9.5a2 2 0 1 1 2.8 1.84c-.54.24-.8.66-.8 1.16M12 14.75h.01" />
        </>
      );
      break;
    case "assignment_deadline":
      drawing = (
        <>
          <rect height="15" rx="1.5" width="16" x="4" y="5.5" />
          <path d="M8 3.5v4M16 3.5v4M4 9.5h16M8 13h3M8 16h6" />
        </>
      );
      break;
  }
  return (
    <span
      aria-hidden="true"
      className="notification-card-icon"
      data-notification-icon={kind}
    >
      <svg viewBox="0 0 24 24">{drawing}</svg>
    </span>
  );
}

function NotificationTile({ item }: { item: NotificationCenterItem }) {
  if (item.sender?.resource_uri && item.sender.image_asset_id) {
    return (
      <span className="notification-card-icon notification-card-portrait">
        <img
          alt=""
          src={courseResourceAssetUrl(
            item.sender.resource_uri,
            item.sender.image_asset_id,
          )}
        />
      </span>
    );
  }
  return <NotificationKindIcon kind={item.kind} />;
}

function senderFirstName(item: NotificationCenterItem): string | null {
  if (
    !item.sender ||
    (item.kind !== "instructor_message" && item.kind !== "staff_reply")
  ) {
    return null;
  }
  return item.sender.first_name;
}

function DismissButton({
  item,
  onMarkRead,
}: {
  item: NotificationCenterItem;
  onMarkRead: (itemId: string) => void;
}) {
  if (!item.dismissible) return null;
  return (
    <Button
      aria-label={`Mark “${item.title}” read`}
      className="notification-card-dismiss"
      onClick={() => onMarkRead(item.id)}
    >
      <CloseIcon />
    </Button>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatDeadline(value: string, now = new Date()): string {
  const deadline = new Date(value);
  if (Number.isNaN(deadline.getTime())) return "Due date unavailable";
  const remainingMs = deadline.getTime() - now.getTime();
  const remainingDays = Math.ceil(remainingMs / 86_400_000);
  if (remainingDays <= 0) return "Due today";
  if (remainingDays === 1) return "Due tomorrow";
  return `Due in ${remainingDays} days`;
}

function formatRelativeTime(value: string, referenceValue: string): string {
  const timestamp = new Date(value);
  const reference = new Date(referenceValue);
  if (Number.isNaN(timestamp.getTime()) || Number.isNaN(reference.getTime())) {
    return formatDate(value);
  }
  const elapsedMs = Math.max(0, reference.getTime() - timestamp.getTime());
  if (elapsedMs < MINUTE_MS) return RELATIVE_TIME_FORMATTER.format(0, "second");
  if (elapsedMs < HOUR_MS) {
    return RELATIVE_TIME_FORMATTER.format(
      -Math.floor(elapsedMs / MINUTE_MS),
      "minute",
    );
  }
  if (elapsedMs < DAY_MS) {
    return RELATIVE_TIME_FORMATTER.format(-Math.floor(elapsedMs / HOUR_MS), "hour");
  }
  const elapsedDays = Math.floor(elapsedMs / DAY_MS);
  if (elapsedDays < 7) return RELATIVE_TIME_FORMATTER.format(-elapsedDays, "day");
  if (elapsedDays < 30) {
    return RELATIVE_TIME_FORMATTER.format(-Math.floor(elapsedDays / 7), "week");
  }
  if (elapsedDays < 365) {
    return RELATIVE_TIME_FORMATTER.format(-Math.floor(elapsedDays / 30), "month");
  }
  return RELATIVE_TIME_FORMATTER.format(-Math.floor(elapsedDays / 365), "year");
}

function itemMeta(item: NotificationCenterItem, generatedAt: string): string {
  if (item.due_at) return formatDate(item.due_at);
  return item.timestamp
    ? formatRelativeTime(item.timestamp, generatedAt)
    : STATE_LABELS[item.state];
}

function assignmentDateParts(value: string): { day: string; month: string } {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { day: "—", month: "Due" };
  return {
    day: new Intl.DateTimeFormat(undefined, { day: "numeric" }).format(date),
    month: new Intl.DateTimeFormat(undefined, { month: "short" }).format(date),
  };
}

function StandardNotificationCardContent({
  generatedAt,
  item,
  showAction,
}: {
  generatedAt: string;
  item: NotificationCenterItem;
  showAction: boolean;
}) {
  const senderName = senderFirstName(item);
  return (
    <span className="notification-card-layout">
      <NotificationTile item={item} />
      <span className="notification-card-content">
        <span className="notification-card-meta">
          <span>
            {STATE_LABELS[item.state]}
            {senderName ? (
              <span className="notification-card-sender">
                <span aria-hidden="true"> · </span>
                {senderName}
              </span>
            ) : null}
          </span>
          <time
            dateTime={item.timestamp ?? undefined}
            title={item.timestamp ? formatDate(item.timestamp) : undefined}
          >
            {itemMeta(item, generatedAt)}
          </time>
        </span>
        <strong className="notification-card-title">{item.title}</strong>
        <span className="notification-card-detail">{item.detail}</span>
        {showAction ? (
          <span className="notification-card-action">{item.action_label}</span>
        ) : null}
      </span>
    </span>
  );
}

export function CommunicationDetailCard({
  generatedAt,
  item,
}: {
  generatedAt: string;
  item: NotificationCenterItem;
}) {
  if (item.section !== "communications") return null;
  return (
    <article
      aria-label={`Communication: ${item.title}`}
      className="notification-card communication-detail-card"
      data-kind={item.kind}
      data-state={item.state}
    >
      <div className="notification-card-primary communication-detail-card-body">
        <StandardNotificationCardContent
          generatedAt={generatedAt}
          item={item}
          showAction={false}
        />
      </div>
    </article>
  );
}

function NotificationCard({
  busy,
  generatedAt,
  item,
  onAction,
  onMarkRead,
}: {
  busy: boolean;
  generatedAt: string;
  item: NotificationCenterItem;
  onAction: (item: NotificationCenterItem) => void;
  onMarkRead: (itemId: string) => void;
}) {
  const deadline = item.due_at
    ? item.state === "past"
      ? "Past due"
      : formatDeadline(item.due_at, new Date(generatedAt))
    : null;
  if (deadline && item.due_at) {
    const date = assignmentDateParts(item.due_at);
    return (
      <li>
        <article
          className="notification-card notification-assignment-card"
          data-kind={item.kind}
          data-state={item.state}
        >
          <button
            aria-label={`${item.action_label}: ${item.title}`}
            className="notification-card-primary"
            disabled={busy}
            onClick={() => onAction(item)}
            type="button"
          >
            <span className="notification-assignment-main">
              <time
                aria-label={`Due ${formatDate(item.due_at)}`}
                className="notification-assignment-date"
                data-notification-icon={item.kind}
                dateTime={item.due_at}
              >
                <span>{date.month}</span>
                <strong>{date.day}</strong>
              </time>
              <span className="notification-assignment-content">
                <span className="notification-assignment-status">
                  <span>{deadline}</span>
                  <span>Assignment</span>
                </span>
                <strong className="notification-card-title">{item.title}</strong>
                <span className="notification-card-detail">{item.detail}</span>
              </span>
            </span>
            <span className="notification-assignment-footer">
              <span>Due {formatDate(item.due_at)}</span>
              <span className="notification-card-action">{item.action_label}</span>
            </span>
          </button>
        </article>
      </li>
    );
  }
  return (
    <li>
      <article
        className="notification-card"
        data-dismissible={item.dismissible ? "true" : undefined}
        data-kind={item.kind}
        data-state={item.state}
      >
        <button
          aria-label={`${item.action_label}: ${item.title}`}
          className="notification-card-primary"
          disabled={busy}
          onClick={() => onAction(item)}
          type="button"
        >
          <StandardNotificationCardContent
            generatedAt={generatedAt}
            item={item}
            showAction
          />
        </button>
        <DismissButton item={item} onMarkRead={onMarkRead} />
      </article>
    </li>
  );
}

export function NotificationCenter({
  busy,
  data,
  historyExpanded,
  onAction,
  onHistoryExpandedChange,
  onMarkRead,
}: NotificationCenterProps) {
  const [hasScrolled, setHasScrolled] = useState(false);
  const [expandedSections, setExpandedSections] = useState<
    Partial<Record<NotificationCenterSection, boolean>>
  >({});
  const historyItems = data.history_items ?? data.items;
  const displayedItems = historyExpanded ? historyItems : data.items;
  const groupedItems = useMemo(
    () =>
      Object.fromEntries(
        SECTIONS.map((section) => [
          section.id,
          displayedItems
            .filter((item) => item.section === section.id)
            .sort((left, right) =>
              historyExpanded ? itemMoment(right) - itemMoment(left) : 0,
            ),
        ]),
      ) as Record<NotificationCenterSection, NotificationCenterItem[]>,
    [displayedItems, historyExpanded],
  );

  if (data.items.length === 0 && historyItems.length === 0) return null;

  function handleScroll(event: UIEvent<HTMLDivElement>) {
    const nextHasScrolled = event.currentTarget.scrollTop > 1;
    setHasScrolled((current) =>
      current === nextHasScrolled ? current : nextHasScrolled,
    );
  }

  return (
    <aside
      aria-label="Notification center"
      aria-live="polite"
      className="notification-center"
      data-current-empty={data.items.length === 0 ? "true" : "false"}
      data-history-open={historyExpanded ? "true" : "false"}
      data-scrolled={hasScrolled ? "true" : "false"}
    >
      <span aria-hidden="true" className="notification-center-header-fade" />
      <div className="notification-center-scroll" onScroll={handleScroll}>
        {SECTIONS.map((section) => {
          const items = groupedItems[section.id];
          if (items.length === 0) return null;
          const sectionExpanded = expandedSections[section.id] === true;
          const visibleItems =
            historyExpanded && !sectionExpanded
              ? items.slice(0, HISTORY_PREVIEW_COUNT)
              : items;
          return (
            <section
              aria-label={section.label}
              className="notification-group"
              key={section.id}
            >
              <header className="notification-group-heading">
                <h2>{section.label}</h2>
                <span>{items.length}</span>
              </header>
              <ol aria-label={section.label} className="notification-items">
                {visibleItems.map((item) => (
                  <NotificationCard
                    busy={busy}
                    generatedAt={data.generated_at}
                    item={item}
                    key={item.id}
                    onAction={onAction}
                    onMarkRead={onMarkRead}
                  />
                ))}
              </ol>
              {historyExpanded && items.length > HISTORY_PREVIEW_COUNT ? (
                <Button
                  aria-expanded={sectionExpanded}
                  aria-label={
                    sectionExpanded
                      ? `Show newest ${HISTORY_PREVIEW_COUNT} ${section.label.toLowerCase()}`
                      : `Show all ${section.label.toLowerCase()}`
                  }
                  className="notification-group-history-toggle"
                  onClick={() =>
                    setExpandedSections((current) => ({
                      ...current,
                      [section.id]: !sectionExpanded,
                    }))
                  }
                >
                  {sectionExpanded ? "Show less" : "See all"}
                </Button>
              ) : null}
            </section>
          );
        })}
        <div className="notification-history-controls">
          <Button
            aria-expanded={historyExpanded}
            className="notification-history-toggle"
            onClick={() => {
              setExpandedSections({});
              onHistoryExpandedChange(!historyExpanded);
            }}
          >
            {historyExpanded ? "Show current" : "See more"}
          </Button>
        </div>
      </div>
    </aside>
  );
}

function itemMoment(item: NotificationCenterItem): number {
  const value = item.due_at ?? item.timestamp;
  if (!value) return 0;
  const moment = Date.parse(value);
  return Number.isNaN(moment) ? 0 : moment;
}
