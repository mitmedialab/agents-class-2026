import type { Event } from "@class-agent/protocol";

export type InstructorMessageStatus =
  | "pending_confirmation"
  | "submitting"
  | "sent"
  | "cancelled"
  | "error";

export type InstructorMessagePublicationDecision =
  | "publish"
  | "silent_publish"
  | "private";

export interface InstructorMessageRecipient {
  email?: string;
  username: string;
  display_name: string;
}

export interface InstructorMessageConfirmation {
  id: string;
  audience: "all_students" | "specific_students";
  recipients: InstructorMessageRecipient[];
  recipientCount: number;
  subject: string;
  message: string;
  publicationDecision?: InstructorMessagePublicationDecision;
  emailAvailable?: boolean;
  status: InstructorMessageStatus;
}

export interface InstructorMessageEdit {
  sendEmail?: boolean;
  subject: string;
  message: string;
  publicationDecision?: InstructorMessagePublicationDecision;
}

export interface InstructorEmailDeliveryReference {
  messageId: string;
  recipientCount: number;
}

export type InstructorEmailDeliveryState =
  | "not_requested"
  | "queued"
  | "sending"
  | "failed"
  | "deferred"
  | "sent";

export interface InstructorEmailDeliveryStatus {
  message_id: string;
  state: InstructorEmailDeliveryState;
  total_recipients: number;
  sent_recipients: number;
  remaining_recipients: number;
  failed_recipients: number;
  deferred_recipients: number;
  total_attempts: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function instructorMessageFromPayload(
  payload: unknown,
): InstructorMessageConfirmation | null {
  if (!isRecord(payload)) return null;
  const id = payload.message_id;
  const audience = payload.audience;
  const recipients = payload.recipients;
  const recipientCount = payload.recipient_count;
  const subject = payload.subject;
  const rawMessage = payload.message;
  const sourceQuestionId = payload.source_question_id;
  const publicationDecision = payload.publication_decision;
  if (
    (payload.email_available !== undefined &&
      typeof payload.email_available !== "boolean") ||
    typeof id !== "string" ||
    (audience !== "all_students" && audience !== "specific_students") ||
    !Array.isArray(recipients) ||
    typeof recipientCount !== "number" ||
    !Number.isInteger(recipientCount) ||
    recipientCount < 1 ||
    typeof subject !== "string" ||
    typeof rawMessage !== "string"
  ) {
    return null;
  }
  const message = rawMessage;
  let parsedPublicationDecision: InstructorMessagePublicationDecision | undefined;
  if (sourceQuestionId !== undefined || publicationDecision !== undefined) {
    if (
      typeof sourceQuestionId !== "string" ||
      publicationDecision !== "publish" &&
      publicationDecision !== "silent_publish" &&
      publicationDecision !== "private"
    ) {
      return null;
    }
    parsedPublicationDecision = publicationDecision;
  }
  const parsedRecipients: InstructorMessageRecipient[] = [];
  for (const recipient of recipients) {
    if (
      !isRecord(recipient) ||
      typeof recipient.username !== "string" ||
      typeof recipient.display_name !== "string" ||
      (recipient.email !== undefined && typeof recipient.email !== "string")
    ) {
      return null;
    }
    parsedRecipients.push({
      username: recipient.username,
      display_name: recipient.display_name,
      ...(typeof recipient.email === "string" ? { email: recipient.email } : {}),
    });
  }
  if (parsedRecipients.length !== recipientCount) return null;
  return {
    id,
    audience,
    recipients: parsedRecipients,
    recipientCount,
    subject,
    message,
    ...(parsedPublicationDecision
      ? { publicationDecision: parsedPublicationDecision }
      : {}),
    ...(typeof payload.email_available === "boolean"
      ? { emailAvailable: payload.email_available }
      : {}),
    status: "pending_confirmation",
  };
}

export function applyInstructorMessageEvent(
  current: InstructorMessageConfirmation | null,
  event: Pick<Event, "type" | "payload">,
): InstructorMessageConfirmation | null {
  if (event.type === "instructor.message.confirmation_requested") {
    return instructorMessageFromPayload(event.payload) ?? current;
  }
  if (!current || event.payload.message_id !== current.id) return current;
  if (
    event.type === "instructor.message.sent" ||
    event.type === "instructor.message.cancelled"
  ) {
    return null;
  }
  return current;
}

export function projectInstructorMessageEvents(
  events: Event[],
): InstructorMessageConfirmation | null {
  return events.reduce<InstructorMessageConfirmation | null>(
    applyInstructorMessageEvent,
    null,
  );
}

export function instructorEmailDeliveryFromEvent(
  event: Pick<Event, "type" | "payload">,
): InstructorEmailDeliveryReference | null {
  const messageId = event.payload.message_id;
  const recipientCount = event.payload.recipient_count;
  if (
    event.type !== "instructor.message.sent" ||
    event.payload.email_queued !== true ||
    typeof messageId !== "string" ||
    typeof recipientCount !== "number" ||
    !Number.isInteger(recipientCount) ||
    recipientCount < 1
  ) {
    return null;
  }
  return { messageId, recipientCount };
}

export function latestInstructorEmailDelivery(
  events: Event[],
): InstructorEmailDeliveryReference | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    const reference = event ? instructorEmailDeliveryFromEvent(event) : null;
    if (reference) return reference;
  }
  return null;
}

export function pendingInstructorMessageContinuation(events: Event[]): Event | null {
  const completed = new Set(
    events.flatMap((event) => {
      const triggerEventId = event.metadata.trigger_event_id;
      return event.type === "agent.message" && typeof triggerEventId === "string"
        ? [triggerEventId]
        : [];
    }),
  );
  let hasLaterUserTurn = false;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event?.type === "user.message") {
      hasLaterUserTurn = true;
      continue;
    }
    if (
      event &&
      (event.type === "instructor.message.sent" ||
        event.type === "instructor.message.cancelled") &&
      !completed.has(event.id)
    ) {
      return hasLaterUserTurn ? null : event;
    }
  }
  return null;
}
