import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PeoplePanel } from "./People.js";

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: vi.fn().mockResolvedValue(body) };
}

const memory = {
  id: "m1",
  kind: "can_help",
  content: "Got MCP OAuth working with the course server.",
  privacy: "personal",
  source_excerpt: "I finally fixed MCP OAuth",
  edited_by_student: false,
  created_at: "2026-11-09T12:00:00Z",
  updated_at: "2026-11-09T12:00:00Z",
};

const draft = {
  id: "i1",
  direction: "outgoing",
  other: { username: "bo-demo", display_name: "Bo Demo" },
  topic: "MCP OAuth",
  message: "Could you show me how you set up OAuth?",
  status: "draft",
  created_at: "2026-11-09T12:00:00Z",
  responded_at: null,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PeoplePanel", () => {
  it("shows memories with their source and lets the student share one", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ memories: [memory], introductions: [] }))
      .mockResolvedValueOnce(
        jsonResponse({ memory: { ...memory, privacy: "course_private", edited_by_student: true } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<PeoplePanel />);

    expect(await screen.findByText(memory.content)).toBeTruthy();
    expect(screen.getByText(/I finally fixed MCP OAuth/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Visible to"), {
      target: { value: "course_private" },
    });
    await waitFor(() => expect(screen.getByText(/Edited by you/)).toBeTruthy());
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toContain("/people/mine/memories/m1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ privacy: "course_private" });
  });

  it("sends a drafted introduction only after the student clicks Send", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ memories: [], introductions: [draft] }))
      .mockResolvedValueOnce(jsonResponse({ introductions: [{ ...draft, status: "sent" }] }));
    vi.stubGlobal("fetch", fetchMock);

    render(<PeoplePanel />);

    expect(await screen.findByText("Draft, not sent")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Waiting for a reply")).toBeTruthy();
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toContain("/people/mine/introductions/i1");
    expect(JSON.parse(String(init.body))).toEqual({ action: "send" });
  });

  it("explains when the panel is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "not found" }, 404)));
    render(<PeoplePanel />);
    expect(await screen.findByText("People is available to active students.")).toBeTruthy();
  });
});
