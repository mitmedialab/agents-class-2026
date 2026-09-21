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
  const [sendEmail, setSendEmail] = useState(false);
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
          .map((recipient) =>
            `${recipient.display_name} (${recipient.username})${recipient.email ? ` — ${recipient.email}` : ""}`,
          )
          .join(", ");

  return (
    <section
      aria-label="Student message confirmation"
      className="ta-question-confirmation"
    >
      <p
        className="message-visibility-help"
        id={`message-edit-help-${confirmation.id}`}
      >
        Edit the subject and full message below, including the greeting and sign-off.
      </p>
      <div className="ta-question-content message-confirmation-editor">
        <label className="message-confirmation-field">
          <span className="ta-question-status">Subject</span>
          <input
            aria-label="Subject"
            className="message-confirmation-inline message-confirmation-subject"
            disabled={busy}
            maxLength={200}
            onChange={(event) => setSubject(event.target.value)}
            required
            value={subject}
          />
        </label>
        <label className="message-confirmation-field">
          <span className="ta-question-status">Message</span>
          <textarea
            aria-describedby={`message-edit-help-${confirmation.id}`}
            aria-label="Message"
            className="message-confirmation-inline message-confirmation-body"
            disabled={busy}
            maxLength={10_000}
            onChange={(event) => setMessage(event.target.value)}
            required
            rows={6}
            value={message}
          />
        </label>
        <p className="ta-question-status">To: {audience}</p>
        {confirmation.audience === "all_students" &&
        confirmation.recipients.some((recipient) => recipient.email) ? (
          <details className="message-visibility-help">
            <summary>Recipient email addresses</summary>
            <ul>
              {confirmation.recipients.map((recipient) => (
                <li key={recipient.username}>
                  {recipient.display_name} ({recipient.username})
                  {recipient.email ? ` — ${recipient.email}` : ""}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
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
            <label>
              <input
                checked={publicationDecision === "silent_publish"}
                disabled={busy}
                name={`message-visibility-${confirmation.id}`}
                onChange={() => setPublicationDecision("silent_publish")}
                type="radio"
                value="silent_publish"
              />
              <span>Silently push to FAQ</span>
            </label>
          </div>
          <p className="message-visibility-help">
            {publicationDecision === "publish"
              ? "Share the redacted question and answer with the course and notify students."
              : publicationDecision === "silent_publish"
                ? "Add the redacted question and answer to the FAQ without notifying students."
                : "Send the answer only to this student."}
          </p>
        </fieldset>
      ) : null}
      {!publicationDecision ? (
        <div className="message-visibility">
          <label className="ta-question-identity">
            <input
              type="checkbox"
              checked={sendEmail}
              disabled={busy || !confirmation.emailAvailable}
              onChange={(event) => setSendEmail(event.target.checked)}
              aria-describedby={`email-help-${confirmation.id}`}
            />
            Also send by email
          </label>
          <p
            className="message-visibility-help"
            id={`email-help-${confirmation.id}`}
          >
            {confirmation.emailAvailable
              ? "Students will also receive a separate email copy. The message stays in the platform."
              : "Email delivery is not configured. This message will be delivered in the platform."}
          </p>
        </div>
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
              ...(confirmation.emailAvailable && !publicationDecision
                ? { sendEmail }
                : {}),
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
