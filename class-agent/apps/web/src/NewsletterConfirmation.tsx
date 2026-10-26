import { Button } from "@class-agent/ui";

import type { NewsletterConfirmation as Confirmation } from "./newsletter.js";

interface NewsletterConfirmationProps {
  confirmation: Confirmation;
  onAction: (action: "send" | "cancel") => void;
}

export function NewsletterConfirmation({
  confirmation,
  onAction,
}: NewsletterConfirmationProps) {
  const busy = confirmation.status === "submitting";
  const status =
    confirmation.status === "error"
      ? "That action could not be saved. Please try again."
      : null;
  const audience =
    confirmation.audience === "all_students"
      ? `All active students and the staff list (${confirmation.recipientCount})`
      : `Test copy to ${confirmation.recipients.join(", ")}`;

  return (
    <section aria-label="Newsletter confirmation" className="ta-question-confirmation">
      <p className="message-visibility-help">
        {confirmation.week !== null
          ? `Week ${confirmation.week} newsletter, ready to send.`
          : "Newsletter ready to send."}{" "}
        Delivery is queued for the mail worker once you press Send.
      </p>
      <div className="ta-question-content message-confirmation-editor">
        <p className="ta-question-status">Subject: {confirmation.subject}</p>
        <p className="message-confirmation-subject">{confirmation.headline}</p>
        <p className="ta-question-status">To: {audience}</p>
        {confirmation.preview ? (
          <details className="message-visibility-help">
            <summary>Preview the text version</summary>
            <pre className="message-confirmation-body">{confirmation.preview}</pre>
          </details>
        ) : null}
      </div>
      {status ? (
        <p aria-live="polite" className="ta-question-status" role="status">
          {status}
        </p>
      ) : null}
      <div className="ta-question-actions">
        <Button autoFocus disabled={busy} onClick={() => onAction("send")} variant="outline">
          {busy ? "Saving…" : "Send"}
        </Button>
        <Button disabled={busy} onClick={() => onAction("cancel")}>
          Cancel
        </Button>
      </div>
    </section>
  );
}
