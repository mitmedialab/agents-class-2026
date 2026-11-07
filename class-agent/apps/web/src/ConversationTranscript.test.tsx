import type { Event } from "@class-agent/protocol";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  ConversationTranscript,
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

describe("ConversationTranscript", () => {
  it("keeps every message in order, including one that never got a reply", () => {
    expect(projectConversationTranscript(events).map(({ from, text }) => [from, text])).toEqual([
      ["agent", "Hello."],
      ["student", "First question"],
      ["agent", "First **answer**."],
      ["student", "Question with no reply"],
    ]);
  });

  it("shows the title and all messages, and closes", () => {
    const onClose = vi.fn();
    render(<ConversationTranscript events={events} onClose={onClose} title="Planning my build" />);

    const dialog = screen.getByRole("dialog", { name: "Full conversation" });
    expect(within(dialog).getByRole("heading", { name: "Planning my build" })).toBeInTheDocument();
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(4);
    expect(within(dialog).getByText("answer").tagName).toBe("STRONG");

    fireEvent.click(within(dialog).getByRole("button", { name: "Continue this conversation" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
