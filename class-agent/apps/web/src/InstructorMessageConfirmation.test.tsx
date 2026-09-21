import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InstructorMessageConfirmation } from "./InstructorMessageConfirmation.js";

describe("InstructorMessageConfirmation", () => {
  it("edits the message while keeping the exact audience fixed", () => {
    const onAction = vi.fn();
    render(
      <InstructorMessageConfirmation
        confirmation={{
          id: "30000000-0000-4000-8000-000000000001",
          audience: "specific_students",
          recipients: [{ username: "alice", display_name: "Alice Example" }],
          recipientCount: 1,
          subject: "Studio reminder",
          message: "Bring your prototype to class.",
          status: "pending_confirmation",
        }}
        onAction={onAction}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: "Subject" }), {
      target: { value: "Updated studio reminder" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "Bring your revised prototype to class." },
    });
    expect(screen.getByText("To: Alice Example (alice)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onAction).toHaveBeenCalledWith("send", {
      subject: "Updated studio reminder",
      message: "Bring your revised prototype to class.",
    });
  });

  it("does not send an empty edited message", () => {
    const onAction = vi.fn();
    render(
      <InstructorMessageConfirmation
        confirmation={{
          id: "30000000-0000-4000-8000-000000000001",
          audience: "all_students",
          recipients: [{ username: "alice", display_name: "Alice Example" }],
          recipientCount: 1,
          subject: "Studio reminder",
          message: "Bring your prototype to class.",
          status: "pending_confirmation",
        }}
        onAction={onAction}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "   " },
    });
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("selects question-reply visibility separately from the answer", () => {
    const onAction = vi.fn();
    render(
      <InstructorMessageConfirmation
        confirmation={{
          id: "30000000-0000-4000-8000-000000000002",
          audience: "specific_students",
          recipients: [{ username: "alice", display_name: "Alice Example" }],
          recipientCount: 1,
          subject: "Re: Model choice",
          message: "A local model is fine.",
          publicationDecision: "private",
          status: "pending_confirmation",
        }}
        onAction={onAction}
      />,
    );

    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(
      "A local model is fine.",
    );
    expect(screen.getByRole("radio", { name: "Private" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "Public" }));
    expect(
      screen.getByText(
        "Share the redacted question and answer with the course and notify students.",
      ),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(onAction).toHaveBeenCalledWith("send", {
      subject: "Re: Model choice",
      message: "A local model is fine.",
      publicationDecision: "publish",
    });
  });

  it("can publish a question reply to the FAQ without notifying students", () => {
    const onAction = vi.fn();
    render(
      <InstructorMessageConfirmation
        confirmation={{
          id: "30000000-0000-4000-8000-000000000003",
          audience: "specific_students",
          recipients: [{ username: "alice", display_name: "Alice Example" }],
          recipientCount: 1,
          subject: "Re: Model choice",
          message: "A local model is fine.",
          publicationDecision: "private",
          status: "pending_confirmation",
        }}
        onAction={onAction}
      />,
    );

    fireEvent.click(screen.getByRole("radio", { name: "Silently push to FAQ" }));
    expect(
      screen.getByText(
        "Add the redacted question and answer to the FAQ without notifying students.",
      ),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(onAction).toHaveBeenCalledWith("send", {
      subject: "Re: Model choice",
      message: "A local model is fine.",
      publicationDecision: "silent_publish",
    });
  });
});

it.each(["all_students", "specific_students"] as const)(
  "offers opt-in email for %s and does not include it on Cancel",
  (audience) => {
    const onAction = vi.fn();
    render(
      <InstructorMessageConfirmation
        confirmation={{
          id: "email-preview",
          audience,
          recipients: [{ username: "alice", display_name: "Alice" }],
          recipientCount: 1,
          subject: "Reminder",
          message: "Bring your prototype.",
          emailAvailable: true,
          status: "pending_confirmation",
        }}
        onAction={onAction}
      />,
    );
    const checkbox = screen.getByRole("checkbox", { name: "Also send by email" });
    expect(checkbox).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onAction).toHaveBeenLastCalledWith(
      "send",
      expect.objectContaining({ sendEmail: false }),
    );
    fireEvent.click(checkbox);
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), {
      target: { value: "Edited message" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onAction).toHaveBeenLastCalledWith("send", {
      subject: "Reminder",
      message: "Edited message",
      sendEmail: true,
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onAction).toHaveBeenLastCalledWith("cancel");
  },
);

it("disables email when unavailable or while sending", () => {
  const confirmation = {
    id: "email-preview",
    audience: "all_students" as const,
    recipients: [{ username: "alice", display_name: "Alice" }],
    recipientCount: 1,
    subject: "Reminder",
    message: "Hello",
    status: "pending_confirmation" as const,
  };
  const { rerender } = render(
    <InstructorMessageConfirmation
      confirmation={confirmation}
      onAction={vi.fn()}
    />,
  );
  expect(screen.getByRole("checkbox", { name: "Also send by email" })).toBeDisabled();
  expect(screen.getByText(/Email delivery is not configured/)).toBeVisible();
  rerender(
    <InstructorMessageConfirmation
      confirmation={{ ...confirmation, emailAvailable: true, status: "submitting" }}
      onAction={vi.fn()}
    />,
  );
  expect(screen.getByRole("checkbox", { name: "Also send by email" })).toBeDisabled();
});


it.each(["Best,\nChitra", ""])("sends the full edited email with sign-off %j", (signOff) => {
  const onAction = vi.fn();
  render(
    <InstructorMessageConfirmation
      confirmation={{
        id: "full-email-preview",
        audience: "all_students",
        recipients: [{ username: "alice", display_name: "Alice" }],
        recipientCount: 1,
        subject: "Reminder",
        message: "Hi everyone,\n\nBring your prototype.\n\nRegards,\nCourse staff",
        emailAvailable: true,
        status: "pending_confirmation",
      }}
      onAction={onAction}
    />,
  );
  const body = screen.getByRole("textbox", { name: "Message" });
  expect(body).toHaveValue("Hi everyone,\n\nBring your prototype.\n\nRegards,\nCourse staff");
  expect(body).toHaveAccessibleDescription(/including the greeting and sign-off/);
  const edited = `Hello students,\n\nBring your revised prototype.${signOff ? `\n\n${signOff}` : ""}`;
  fireEvent.change(body, { target: { value: edited } });
  fireEvent.change(screen.getByRole("textbox", { name: "Subject" }), {
    target: { value: "Updated reminder" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: "Also send by email" }));
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  expect(onAction).toHaveBeenCalledWith("send", {
    subject: "Updated reminder", message: edited, sendEmail: true,
  });
});

it.each(["all_students", "specific_students"] as const)(
  "shows recipient emails to the instructor for %s",
  (audience) => {
    render(
      <InstructorMessageConfirmation
        confirmation={{
          id: "recipient-preview", audience,
          recipients: [{ username: "alice", display_name: "Alice", email: "alice@example.com" }],
          recipientCount: 1, subject: "Reminder", message: "Hello Alice,\n\nPlease accept.\n\nBest,\nInstructor",
          status: "pending_confirmation", emailAvailable: true,
        }}
        onAction={vi.fn()}
      />,
    );
    if (audience === "all_students") {
      fireEvent.click(screen.getByText("Recipient email addresses"));
    }
    expect(screen.getByText(/alice@example.com/)).toBeVisible();
  },
);
