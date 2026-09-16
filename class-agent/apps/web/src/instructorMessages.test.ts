import type { Event } from "@class-agent/protocol";
import { describe, expect, it } from "vitest";

import {
  applyInstructorMessageEvent,
  instructorMessageFromPayload,
  pendingInstructorMessageContinuation,
  projectInstructorMessageEvents,
} from "./instructorMessages.js";

function event(type: string, payload: Event["payload"], id: string): Event {
  return {
    id,
    schema_version: 1,
    timestamp: "2026-09-14T12:00:00Z",
    type,
    actor: "course-agent",
    principal_user_id: "10000000-0000-4000-8000-000000000001",
    anonymous_session_id: null,
    conversation_id: "20000000-0000-4000-8000-000000000001",
    node_id: null,
    payload,
    metadata: {},
  };
}

const confirmationPayload = {
  message_id: "30000000-0000-4000-8000-000000000001",
  audience: "specific_students",
  recipients: [{ username: "alice", display_name: "Alice Example" }],
  recipient_count: 1,
  subject: "Studio reminder",
  message: "Bring your prototype to class.",
};

describe("instructor message events", () => {
  it("parses only complete trusted confirmation payloads", () => {
    expect(instructorMessageFromPayload(confirmationPayload)).toMatchObject({
      id: confirmationPayload.message_id,
      recipientCount: 1,
      status: "pending_confirmation",
    });
    expect(
      instructorMessageFromPayload({ ...confirmationPayload, recipient_count: 2 }),
    ).toBeNull();
  });

  it("parses question-reply visibility independently from the answer body", () => {
    expect(
      instructorMessageFromPayload({
        ...confirmationPayload,
        source_question_id: "50000000-0000-4000-8000-000000000001",
        publication_decision: "private",
        message: "A local model is fine.",
      }),
    ).toMatchObject({
      message: "A local model is fine.",
      publicationDecision: "private",
    });
    expect(
      instructorMessageFromPayload({
        ...confirmationPayload,
        source_question_id: "50000000-0000-4000-8000-000000000001",
      }),
    ).toBeNull();
  });

  it("projects and resolves the pending confirmation", () => {
    const requested = event(
      "instructor.message.confirmation_requested",
      confirmationPayload,
      "40000000-0000-4000-8000-000000000001",
    );
    const sent = event(
      "instructor.message.sent",
      { message_id: confirmationPayload.message_id },
      "40000000-0000-4000-8000-000000000002",
    );

    const pending = projectInstructorMessageEvents([requested]);
    expect(pending?.subject).toBe("Studio reminder");
    expect(applyInstructorMessageEvent(pending, sent)).toBeNull();
  });

  it("finds only delivery actions that still need an agent continuation", () => {
    const sent = event(
      "instructor.message.sent",
      { message_id: confirmationPayload.message_id },
      "40000000-0000-4000-8000-000000000002",
    );
    expect(pendingInstructorMessageContinuation([sent])?.id).toBe(sent.id);
    const completed = event(
      "agent.message",
      { text: "Sent." },
      "40000000-0000-4000-8000-000000000003",
    );
    completed.metadata.trigger_event_id = sent.id;
    expect(pendingInstructorMessageContinuation([sent, completed])).toBeNull();
  });
});
