import { Button } from "@class-agent/ui";
import { useState } from "react";

import type {
  InstructorMessageConfirmation as Confirmation,
  InstructorMessageEdit,
  InstructorMessagePublicationDecision,
} from "./instructorMessages.js";

interface InstructorMessageConfirmationProps {
  confirmation: Confirmation;
  onAction: (action: "send" | "cancel", edit?: InstructorMessageEdit) => void;
}

export function InstructorMessageConfirmation({
  confirmation,
  onAction,
}: InstructorMessageConfirmationProps) {
  const [subject, setSubject] = useState(confirmation.subject);
  const [message, setMessage] = useState(confirmation.message);
  const [publicationDecision, setPublicationDecision] =
    useState<InstructorMessagePublicationDecision | null>(
      confirmation.publicationDecision ?? null,
    );
  const busy = confirmation.status === "submitting";
  const sendDisabled = busy || !subject.trim() || !message.trim();
  const status =
    confirmation.status === "error"
      ? "That action could not be saved. Please try again."
      : null;
  const audience =
    confirmation.audience === "all_students"
      ? `All active students (${confirmation.recipientCount})`
      : confirmation.recipients
          .map((recipient) => `${recipient.display_name} (${recipient.username})`)
          .join(", ");

  return (
    <section
      aria-label="Student message confirmation"
      className="ta-question-confirmation"
    >
      <div className="ta-question-content">
        <input
          aria-label="Subject"
          className="message-confirmation-inline message-confirmation-subject"
          disabled={busy}
          maxLength={200}
          onChange={(event) => setSubject(event.target.value)}
          required
          value={subject}
        />
        <textarea
          aria-label="Message"
          className="message-confirmation-inline message-confirmation-body"
          disabled={busy}
          maxLength={10_000}
          onChange={(event) => setMessage(event.target.value)}
          required
          rows={1}
          value={message}
        />
        <p className="ta-question-status">To: {audience}</p>
      </div>
      {publicationDecision ? (
        <fieldset className="message-visibility">
          <legend>Visibility</legend>
          <div className="message-visibility-options">
            <label>
              <input
                checked={publicationDecision === "private"}
                disabled={busy}
                name={`message-visibility-${confirmation.id}`}
                onChange={() => setPublicationDecision("private")}
                type="radio"
                value="private"
              />
              <span>Private</span>
            </label>
            <label>
              <input
                checked={publicationDecision === "publish"}
                disabled={busy}
                name={`message-visibility-${confirmation.id}`}
                onChange={() => setPublicationDecision("publish")}
                type="radio"
                value="publish"
              />
              <span>Public</span>
            </label>
          </div>
          <p className="message-visibility-help">
            {publicationDecision === "publish"
              ? "Share the redacted question and answer with the course."
              : "Send the answer only to this student."}
          </p>
        </fieldset>
      ) : null}
      {status ? (
        <p aria-live="polite" className="ta-question-status" role="status">
          {status}
        </p>
      ) : null}
      <div className="ta-question-actions">
        <Button
          autoFocus
          disabled={sendDisabled}
          onClick={() =>
            onAction("send", {
              subject,
              message,
              ...(publicationDecision ? { publicationDecision } : {}),
            })
          }
          variant="outline"
        >
          {busy ? "Saving…" : "Send"}
        </Button>
        <Button disabled={busy} onClick={() => onAction("cancel")}>
          Cancel
        </Button>
      </div>
    </section>
  );
}
