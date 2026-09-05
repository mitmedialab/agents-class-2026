import type { Event, JsonObject } from "@class-agent/protocol";
import { describe, expect, it } from "vitest";
import {
  pendingTAQuestionContinuation,
  projectTAQuestionEvents,
} from "./taQuestions.js";

function event(type: string, payload: JsonObject): Event {
  return {
    schema_version: 1,
    id: crypto.randomUUID(),
    timestamp: "2026-09-04T15:00:00Z",
    type,
    actor: "test",
    principal_user_id: "10000000-0000-4000-8000-000000000001",
    anonymous_session_id: null,
    conversation_id: "20000000-0000-4000-8000-000000000001",
    node_id: null,
    payload,
    metadata: {},
  };
}

const questionId = "50000000-0000-4000-8000-000000000001";
const confirmation = event("email.ta_question.confirmation_requested", {
  question_id: questionId,
  question_code: "Q-2026-00001",
  subject: "Assignment model",
  question: "May I use a local model?",
  status: "pending_confirmation",
});

describe("TA question event projection", () => {
  it("closes the confirmation once the question is accepted", () => {
    expect(
      projectTAQuestionEvents([
        confirmation,
        event("email.ta_question.queued", {
          question_id: questionId,
          status: "open",
        }),
      ]),
    ).toBeNull();
  });

  it("finds only trusted actions that do not yet have an agent continuation", () => {
    const queued = event("email.ta_question.queued", {
      question_id: questionId,
      question: "May I use a local model?",
      status: "queued",
    });
    expect(pendingTAQuestionContinuation([confirmation, queued])).toEqual(queued);

    const continued = {
      ...event("agent.message", { text: "Course staff have the question." }),
      metadata: { trigger_event_id: queued.id },
    };
    expect(
      pendingTAQuestionContinuation([confirmation, queued, continued]),
    ).toBeNull();
  });

  it("closes a cancelled confirmation immediately", () => {
    expect(
      projectTAQuestionEvents([
        confirmation,
        event("email.ta_question.cancelled", {
          question_id: questionId,
          status: "closed",
        }),
      ]),
    ).toBeNull();
  });
});
