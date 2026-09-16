import { Button } from "@class-agent/ui";
import { useState } from "react";

import type {
  TAQuestionConfirmation as Confirmation,
  TAQuestionEdit,
} from "./taQuestions.js";

interface TAQuestionConfirmationProps {
  confirmation: Confirmation;
  onAction: (
    action: "send" | "cancel",
    reporterVisibility: "named" | "anonymous",
    edit?: TAQuestionEdit,
  ) => void;
}

export function TAQuestionConfirmation({
  confirmation,
  onAction,
}: TAQuestionConfirmationProps) {
  const [anonymous, setAnonymous] = useState(false);
  const [question, setQuestion] = useState(confirmation.question);
  const busy = confirmation.status === "submitting";
  const sendDisabled = busy || !question.trim();
  const resolved =
    confirmation.status === "queued" ||
    confirmation.status === "sent" ||
    confirmation.status === "answered" ||
    confirmation.status === "cancelled";
  if (resolved) return null;
  const status =
    confirmation.status === "error"
      ? "That action could not be saved. Please try again."
      : null;

  return (
    <section
      aria-label="Course staff question confirmation"
      className="ta-question-confirmation"
    >
      <div className="ta-question-content">
        <textarea
          aria-label="Question"
          className="message-confirmation-inline message-confirmation-body"
          disabled={busy}
          maxLength={5_000}
          onChange={(event) => setQuestion(event.target.value)}
          required
          rows={1}
          value={question}
        />
      </div>
      {status ? (
        <p aria-live="polite" className="ta-question-status" role="status">
          {status}
        </p>
      ) : null}
      <label className="ta-question-identity">
        <input
          checked={anonymous}
          disabled={busy}
          onChange={(event) => setAnonymous(event.target.checked)}
          type="checkbox"
        />
        Hide my name from course staff
      </label>
      <div className="ta-question-actions">
        <Button
          autoFocus
          disabled={sendDisabled}
          onClick={() =>
            onAction("send", anonymous ? "anonymous" : "named", {
              question,
            })
          }
          variant="outline"
        >
          {busy ? "Saving…" : "Send"}
        </Button>
        <Button disabled={busy} onClick={() => onAction("cancel", "named")}>
          Cancel
        </Button>
      </div>
    </section>
  );
}
