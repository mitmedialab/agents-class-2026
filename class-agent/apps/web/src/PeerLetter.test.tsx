import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NotificationCenterItem } from "./api.js";
import {
  markPeerLetterSeen,
  nextPeerLetter,
  PeerLetter,
  readSeenPeerLetters,
} from "./PeerLetter.js";

function item(overrides: Partial<NotificationCenterItem>): NotificationCenterItem {
  return {
    id: "60000000-0000-4000-8000-000000000061",
    section: "communications",
    kind: "peer_request",
    state: "pending",
    title: "Memory architectures",
    detail: "Could you walk me through your memory design?",
    timestamp: "2026-11-09T12:00:00Z",
    due_at: null,
    action_label: "Open People",
    action_prompt: "Open People.",
    unread: true,
    dismissible: false,
    sender: {
      first_name: "Stacey",
      display_name: "Stacey Cho",
      resource_uri: null,
      image_asset_id: null,
    },
    ...overrides,
  };
}

afterEach(() => window.localStorage.clear());

describe("nextPeerLetter", () => {
  it("presents pending requests and unread acceptances once, and nothing else", () => {
    const request = item({});
    const reply = item({ id: "r1", kind: "peer_reply", state: "responded" });
    const readReply = item({ id: "r2", kind: "peer_reply", state: "responded", unread: false });
    const update = item({ id: "u1", kind: "course_update", section: "notifications" });

    expect(nextPeerLetter([update, request], [])).toBe(request);
    expect(nextPeerLetter([update, request, reply], [request.id])).toBe(reply);
    expect(nextPeerLetter([update, readReply], [])).toBeNull();
    expect(nextPeerLetter([request, reply], [request.id, reply.id])).toBeNull();
  });

  it("remembers seen letters in this browser and survives unavailable storage", () => {
    markPeerLetterSeen("a");
    markPeerLetterSeen("b");
    expect(readSeenPeerLetters()).toEqual(["a", "b"]);

    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readSeenPeerLetters()).toEqual([]);
    getItem.mockRestore();
  });
});

describe("PeerLetter", () => {
  it("shows a request with the helper framing and focuses the answer action", () => {
    const onOpen = vi.fn();
    const onClose = vi.fn();
    render(<PeerLetter item={item({})} onClose={onClose} onOpen={onOpen} />);

    const dialog = screen.getByRole("dialog", { name: "Memory architectures" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("A letter from Stacey Cho")).toBeVisible();
    expect(screen.getByText(/walk me through your memory design/)).toBeVisible();
    expect(screen.getByText(/best ways to understand it yourself/)).toBeVisible();
    const answer = screen.getByRole("button", { name: "Answer in People" });
    expect(answer).toHaveFocus();
    fireEvent.click(answer);
    expect(onOpen).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows an acceptance as a reply", () => {
    render(
      <PeerLetter
        item={item({
          kind: "peer_reply",
          state: "responded",
          detail: "Jad Bendarkawi agreed to help.",
          sender: {
            first_name: "Jad",
            display_name: "Jad Bendarkawi",
            resource_uri: null,
            image_asset_id: null,
          },
        })}
        onClose={vi.fn()}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("Jad Bendarkawi wrote back")).toBeVisible();
    expect(screen.getByText("Jad Bendarkawi agreed to help.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Open in People" })).toBeVisible();
  });
});
