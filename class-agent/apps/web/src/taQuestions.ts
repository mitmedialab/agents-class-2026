import type { Event } from "@class-agent/protocol";

export type TAQuestionStatus =
  | "pending_confirmation"
  | "submitting"
  | "queued"
  | "sent"
  | "answered"
  | "cancelled"
  | "error";

export interface TAQuestionConfirmation {
  id: string;
  code: string;
  subject: string;
  question: string;
  context?: string;
  status: TAQuestionStatus;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function confirmationFromPayload(
  payload: unknown,
): TAQuestionConfirmation | null {
  if (!isRecord(payload)) return null;
  const id = payload.question_id;
  const code = payload.question_code;
  const subject = payload.subject;
  const question = payload.question;
  const context = payload.context;
  if (
    typeof id !== "string" ||
    typeof code !== "string" ||
    typeof subject !== "string" ||
    typeof question !== "string" ||
    (context !== undefined && typeof context !== "string")
  ) {
    return null;
  }
  return {
    id,
    code,
    subject,
    question,
    ...(typeof context === "string" ? { context } : {}),
    status: "pending_confirmation",
  };
}

export function applyTAQuestionEvent(
  current: TAQuestionConfirmation | null,
  event: Pick<Event, "type" | "payload">,
): TAQuestionConfirmation | null {
  if (event.type === "email.ta_question.confirmation_requested") {
    return confirmationFromPayload(event.payload) ?? current;
  }
  if (!current || event.payload.question_id !== current.id) return current;
  if (event.type === "email.ta_question.queued") {
    return null;
  }
  if (event.type === "email.ta_question.cancelled") {
    return null;
  }
  if (event.type === "email.ta_question.created") {
    return { ...current, status: "sent" };
  }
  if (event.type === "email.ta_answer.received") {
    return { ...current, status: "answered" };
  }
  return current;
}

export function projectTAQuestionEvents(
  events: Event[],
): TAQuestionConfirmation | null {
  return events.reduce<TAQuestionConfirmation | null>(applyTAQuestionEvent, null);
}

export function pendingTAQuestionContinuation(events: Event[]): Event | null {
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
      (event.type === "email.ta_question.queued" ||
        event.type === "email.ta_question.cancelled") &&
      !completed.has(event.id)
    ) {
      return event;
    }
  }
  return null;
}
