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
      screen.getByText("Share the redacted question and answer with the course."),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(onAction).toHaveBeenCalledWith("send", {
      subject: "Re: Model choice",
      message: "A local model is fine.",
      publicationDecision: "publish",
    });
  });
});
