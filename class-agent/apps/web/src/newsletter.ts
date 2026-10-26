import type { Event } from "@class-agent/protocol";

export interface NewsletterConfirmation {
  issueId: string;
  confirmationId: string;
  audience: "all_students" | "test";
  recipients: string[];
  recipientCount: number;
  subject: string;
  headline: string;
  week: number | null;
  preview: string;
  status: "awaiting_confirmation" | "submitting" | "error";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function newsletterFromPayload(
  payload: Record<string, unknown>,
): NewsletterConfirmation | null {
  const issueId = payload.issue_id;
  const confirmationId = payload.confirmation_id;
  const audience = payload.audience;
  const subject = payload.subject;
  const headline = payload.headline;
  const recipientCount = payload.recipient_count;
  if (
    typeof issueId !== "string" ||
    typeof confirmationId !== "string" ||
    (audience !== "all_students" && audience !== "test") ||
    typeof subject !== "string" ||
    typeof headline !== "string" ||
    typeof recipientCount !== "number"
  ) {
    return null;
  }
  const recipients = Array.isArray(payload.recipients)
    ? payload.recipients.filter((item): item is string => typeof item === "string")
    : [];
  return {
    issueId,
    confirmationId,
    audience,
    recipients,
    recipientCount,
    subject,
    headline,
    week: typeof payload.week === "number" ? payload.week : null,
    preview: typeof payload.preview === "string" ? payload.preview : "",
    status: "awaiting_confirmation",
  };
}

export function applyNewsletterEvent(
  current: NewsletterConfirmation | null,
  event: Pick<Event, "type" | "payload">,
): NewsletterConfirmation | null {
  if (event.type === "instructor.newsletter.confirmation_requested") {
    return isRecord(event.payload) ? (newsletterFromPayload(event.payload) ?? current) : current;
  }
  if (!current || event.payload.issue_id !== current.issueId) return current;
  if (
    event.type === "instructor.newsletter.approved" ||
    event.type === "instructor.newsletter.cancelled"
  ) {
    return null;
  }
  return current;
}

export function projectNewsletterEvents(events: Event[]): NewsletterConfirmation | null {
  return events.reduce<NewsletterConfirmation | null>(applyNewsletterEvent, null);
}

export function pendingNewsletterContinuation(events: Event[]): Event | null {
  const completed = new Set(
    events.flatMap((event) => {
      const triggerEventId = event.metadata.trigger_event_id;
      return event.type === "agent.message" && typeof triggerEventId === "string"
        ? [triggerEventId]
        : [];
    }),
  );
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (
      event &&
      (event.type === "instructor.newsletter.approved" ||
        event.type === "instructor.newsletter.cancelled") &&
      !completed.has(event.id)
    ) {
      return event;
    }
  }
  return null;
}
