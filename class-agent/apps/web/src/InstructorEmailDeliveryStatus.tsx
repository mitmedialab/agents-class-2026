import type { Uuid } from "@class-agent/protocol";
import { useEffect, useState } from "react";

import { getInstructorMessageEmailDelivery } from "./api.js";
import type { InstructorEmailDeliveryStatus } from "./instructorMessages.js";

const DELIVERY_POLL_INTERVAL_MS = 5_000;
const DELIVERY_ERROR_RETRY_MS = 15_000;

interface InstructorEmailDeliveryStatusProps {
  conversationId: Uuid;
  messageId: string;
  recipientCount: number;
}

function statusText(
  status: InstructorEmailDeliveryStatus | null,
  recipientCount: number,
): string {
  if (!status) return `Email queued for ${recipientCount} recipients.`;
  if (status.state === "sent") {
    return `Email sent to all ${status.total_recipients} recipients.`;
  }
  if (status.state === "failed") {
    return `Email delivery failed for ${status.failed_recipients} recipients; ${status.sent_recipients} of ${status.total_recipients} sent.`;
  }
  if (status.state === "deferred") {
    return `Email sent to ${status.sent_recipients} of ${status.total_recipients} recipients; ${status.deferred_recipients} deferred.`;
  }
  if (status.state === "sending") {
    return `Sending email: ${status.sent_recipients} of ${status.total_recipients} sent.`;
  }
  if (status.state === "not_requested") return "No email copy was requested.";
  return `Email queued for ${status.total_recipients} recipients.`;
}

export function InstructorEmailDeliveryStatus({
  conversationId,
  messageId,
  recipientCount,
}: InstructorEmailDeliveryStatusProps) {
  const [delivery, setDelivery] = useState<InstructorEmailDeliveryStatus | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;

    const refresh = async (): Promise<void> => {
      try {
        const next = await getInstructorMessageEmailDelivery(
          conversationId,
          messageId,
        );
        if (!active) return;
        setDelivery(next);
        setUnavailable(false);
        if (
          next.state !== "sent" &&
          next.state !== "deferred" &&
          next.state !== "not_requested"
        ) {
          timer = window.setTimeout(refresh, DELIVERY_POLL_INTERVAL_MS);
        }
      } catch {
        if (!active) return;
        setUnavailable(true);
        timer = window.setTimeout(refresh, DELIVERY_ERROR_RETRY_MS);
      }
    };

    void refresh();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [conversationId, messageId]);

  const failed = delivery?.state === "failed";
  const deferred = delivery?.state === "deferred";
  return (
    <section
      aria-label="Email delivery status"
      aria-live="polite"
      className="instructor-email-delivery"
    >
      <p className="ta-question-status">Email delivery</p>
      <p>
        {unavailable
          ? "Email status is temporarily unavailable. Delivery continues in the background."
          : statusText(delivery, recipientCount)}
      </p>
      <p className="message-visibility-help">
        {failed
          ? "The mail worker will retry automatically. Check the mailbox authorization if this persists."
          : deferred
            ? "Deferred recipients have an inactive account or no longer have the student role. Delivery resumes if their account becomes eligible."
            : "Sent is recorded when the configured mail provider accepts each message."}
      </p>
    </section>
  );
}
