import type { Event } from "@class-agent/protocol";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ConversationChat,
  projectConversationTranscript,
} from "./ConversationTranscript.js";

function event(type: string, payload: Record<string, unknown>, minute: number): Event {
  return {
    id: `00000000-0000-4000-8000-0000000000${String(minute).padStart(2, "0")}`,
    schema_version: 1,
    timestamp: `2026-11-06T21:${String(minute).padStart(2, "0")}:00Z`,
    type,
    actor: "test",
    principal_user_id: null,
    anonymous_session_id: null,
    conversation_id: "00000000-0000-4000-8000-000000000099",
    node_id: null,
    payload,
    metadata: {},
  } as unknown as Event;
}

const events = [
  event("agent.message", { text: "Hello." }, 1),
  event("user.message", { text: "First question\n\n[Temporary upload: abc]" }, 2),
  event("agent.tool.requested", { tool_id: "memory.get_mine" }, 3),
  event("agent.message", { text: "First **answer**." }, 4),
  event("user.message", { text: "Question with no reply" }, 5),
];

describe("ConversationChat", () => {
  const events = [
    event("user.message", { text: "What should I watch?" }, 1),
    event("tool.call", { tool_id: "memory.get_mine" }, 2),
    event("agent.message", { text: "Your Week 5 notes say to watch pass rates." }, 3),
    event("user.message", { text: "<user_request>And then?</user_request>" }, 4),
  ];

  it("projects student and agent messages in order and leaves out tool activity", () => {
    expect(projectConversationTranscript(events).map(({ from, text }) => [from, text])).toEqual([
      ["student", "What should I watch?"],
      ["agent", "Your Week 5 notes say to watch pass rates."],
      ["student", "And then?"],
    ]);
  });

  it("shows every message, including a question that got no reply", () => {
    render(<ConversationChat events={events} latestResponse="" pendingMessage={null} />);

    const chat = within(screen.getByRole("list", { name: "Chat history" }));
    expect(chat.getByText("What should I watch?")).toBeInTheDocument();
    expect(chat.getByText("Your Week 5 notes say to watch pass rates.")).toBeInTheDocument();
    expect(chat.getByText("And then?")).toBeInTheDocument();
  });

  it("adds a run in progress below the saved messages without repeating saved ones", () => {
    const { rerender } = render(
      <ConversationChat events={events} latestResponse="Working" pendingMessage="One more" />,
    );
    expect(screen.getByText("One more")).toBeInTheDocument();
    expect(screen.getByText("Working")).toBeInTheDocument();

    rerender(
      <ConversationChat
        events={events}
        latestResponse="Your Week 5 notes say to watch pass rates."
        pendingMessage="And then?"
      />,
    );
    expect(screen.getAllByText("And then?")).toHaveLength(1);
    expect(screen.getAllByText("Your Week 5 notes say to watch pass rates.")).toHaveLength(1);
  });
});
