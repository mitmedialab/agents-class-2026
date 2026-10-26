import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./api.js";
import { InstructorEmailDeliveryStatus } from "./InstructorEmailDeliveryStatus.js";

vi.mock("./api.js", () => ({
  getInstructorMessageEmailDelivery: vi.fn(),
}));

const props = {
  conversationId: "20000000-0000-4000-8000-000000000001",
  messageId: "30000000-0000-4000-8000-000000000001",
  recipientCount: 34,
};

describe("InstructorEmailDeliveryStatus", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows completed provider acceptance", async () => {
    vi.mocked(api.getInstructorMessageEmailDelivery).mockResolvedValue({
      message_id: props.messageId,
      state: "sent",
      total_recipients: 34,
      sent_recipients: 34,
      remaining_recipients: 0,
      failed_recipients: 0,
      deferred_recipients: 0,
      total_attempts: 34,
    });

    render(<InstructorEmailDeliveryStatus {...props} />);

    expect(
      await screen.findByText("Email sent to all 34 recipients."),
    ).toBeVisible();
    expect(screen.getByText(/mail provider accepts each message/i)).toBeVisible();
  });

  it("shows retrying failures without provider details", async () => {
    vi.mocked(api.getInstructorMessageEmailDelivery).mockResolvedValue({
      message_id: props.messageId,
      state: "failed",
      total_recipients: 34,
      sent_recipients: 0,
      remaining_recipients: 34,
      failed_recipients: 34,
      deferred_recipients: 0,
      total_attempts: 68,
    });

    render(<InstructorEmailDeliveryStatus {...props} />);

    expect(
      await screen.findByText(
        "Email delivery failed for 34 recipients; 0 of 34 sent.",
      ),
    ).toBeVisible();
    expect(screen.getByText(/retry automatically/i)).toBeVisible();
  });
});
