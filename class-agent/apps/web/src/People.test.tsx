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

  it("lets the requester edit the drafted message in place before sending", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ memories: [], introductions: [draft] }))
      .mockResolvedValueOnce(
        jsonResponse({
          introductions: [{ ...draft, status: "sent", message: "Bo, could you pair with me?" }],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<PeoplePanel />);

    const box = await screen.findByRole("textbox", { name: "Message to Bo Demo" });
    expect((box as HTMLTextAreaElement).value).toBe(draft.message);
    fireEvent.change(box, { target: { value: "" } });
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    fireEvent.change(box, { target: { value: "  Bo, could you pair with me?  " } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Bo, could you pair with me?")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Message to Bo Demo" })).toBeNull();
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      action: "send",
      message: "Bo, could you pair with me?",
    });
  });

  it("frames an incoming request for the helper and records Accept", async () => {
    const incoming = {
      ...draft,
      direction: "incoming",
      other: { username: "ada-demo", display_name: "Ada Demo" },
      status: "sent",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ memories: [], introductions: [incoming] }))
      .mockResolvedValueOnce(jsonResponse({ introductions: [{ ...incoming, status: "accepted" }] }));
    vi.stubGlobal("fetch", fetchMock);

    render(<PeoplePanel />);

    expect(await screen.findByText("A classmate is asking you")).toBeTruthy();
    expect(screen.getByText(/one of the best ways to understand it yourself/)).toBeTruthy();
    expect(screen.getByRole("listitem", { current: "step" }).textContent).toBe("Sent");
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(await screen.findByText("You agreed to help Ada Demo.")).toBeTruthy();
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ action: "accept" });
  });

  it("lets the helper add a note that is sent only with Accept", async () => {
    const incoming = {
      ...draft,
      direction: "incoming",
      other: { username: "ada-demo", display_name: "Ada Demo" },
      status: "sent",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ memories: [], introductions: [incoming] }))
      .mockResolvedValueOnce(
        jsonResponse({
          introductions: [{ ...incoming, status: "accepted", reply: "Free Thursday after class." }],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<PeoplePanel />);

    fireEvent.change(await screen.findByLabelText(/Note to Ada Demo/), {
      target: { value: "  Free Thursday after class.  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));

    expect(await screen.findByText("Free Thursday after class.")).toBeTruthy();
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      action: "accept",
      reply: "Free Thursday after class.",
    });
  });

  it("groups memories by who can see them", async () => {
    const shared = { ...memory, id: "m2", privacy: "course_private", content: "Shared fact." };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ memories: [memory, shared], introductions: [] })),
    );

    render(<PeoplePanel />);

    const sharedHeading = await screen.findByRole("heading", { name: /Shared with classmates/ });
    const sharedGroup = sharedHeading.parentElement as HTMLElement;
    expect(sharedGroup.textContent).toContain("Shared fact.");
    expect(sharedGroup.textContent).not.toContain(memory.content);
    const personalGroup = screen.getByRole("heading", { name: /Only you/ }).parentElement;
    expect(personalGroup?.textContent).toContain(memory.content);
  });

  it("explains when the panel is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "not found" }, 404)));
    render(<PeoplePanel />);
    expect(await screen.findByText("People is available to active students.")).toBeTruthy();
  });
});
