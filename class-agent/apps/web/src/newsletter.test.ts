import { describe, expect, it } from "vitest";
import type { Event } from "@class-agent/protocol";

import {
  applyNewsletterEvent,
  newsletterFromPayload,
  pendingNewsletterContinuation,
  projectNewsletterEvents,
} from "./newsletter.js";

function event(type: string, payload: Record<string, unknown>, id = "e-1"): Event {
  return {
    id,
    schema_version: 1,
    type,
    actor: "system",
    payload,
    metadata: {},
    recorded_at: "2026-09-22T15:00:00Z",
  } as unknown as Event;
}

const requested = event("instructor.newsletter.confirmation_requested", {
  issue_id: "2026-week01",
  confirmation_id: "10000000-0000-4000-8000-000000000001",
  audience: "all_students",
  recipient_count: 27,
  recipients: [],
  subject: "The Class Runtime from MAS.S60",
  headline: "Loop There It Is",
  week: 1,
  preview: "THE CLASS RUNTIME",
  status: "awaiting_confirmation",
});

describe("newsletter confirmation", () => {
  it("projects the confirmation from the platform event", () => {
    const confirmation = projectNewsletterEvents([requested]);
    expect(confirmation).toEqual({
      issueId: "2026-week01",
      confirmationId: "10000000-0000-4000-8000-000000000001",
      audience: "all_students",
      recipients: [],
      recipientCount: 27,
      subject: "The Class Runtime from MAS.S60",
      headline: "Loop There It Is",
      week: 1,
      preview: "THE CLASS RUNTIME",
      status: "awaiting_confirmation",
    });
    expect(newsletterFromPayload({ issue_id: "x" })).toBeNull();
  });

  it("clears after approval or cancellation of the same issue only", () => {
    const current = projectNewsletterEvents([requested]);
    const other = event("instructor.newsletter.approved", { issue_id: "2026-week02" }, "e-2");
    expect(applyNewsletterEvent(current, other)).toBe(current);
    const approved = event("instructor.newsletter.approved", { issue_id: "2026-week01" }, "e-3");
    expect(applyNewsletterEvent(current, approved)).toBeNull();
    expect(pendingNewsletterContinuation([requested, approved])).toBe(approved);
    const followed = event("agent.message", {}, "e-4");
    followed.metadata = { trigger_event_id: "e-3" };
    expect(pendingNewsletterContinuation([requested, approved, followed])).toBeNull();
  });
});
