import type { Event } from "@class-agent/protocol";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  ConversationTimeline,
  momentAtOffset,
  projectConversationTimeline,
  timelineFade,
  visibleUserMessage,
} from "./ConversationTimeline.js";

function event(id: string, type: string, payload: Event["payload"]): Event {
  return {
    id,
    schema_version: 1,
    timestamp: `2026-08-23T10:0${id}:00Z`,
    type,
    actor: "course-agent",
    principal_user_id: null,
    anonymous_session_id: null,
    conversation_id: null,
    node_id: null,
    payload,
    metadata: {},
  };
}

describe("conversation timeline", () => {
  it("hides both moments while the layout changes through black", () => {
    expect(timelineFade(0)).toEqual({ outgoing: 1, incoming: 0, layout: 0 });
    expect(timelineFade(0.5)).toEqual({ outgoing: 0, incoming: 0, layout: 0.5 });
    expect(timelineFade(1).outgoing).toBe(0);
    expect(timelineFade(1).incoming).toBeCloseTo(1);
    expect(timelineFade(1).layout).toBe(1);
    expect(timelineFade(0.4).outgoing).toBeGreaterThan(0);
    expect(timelineFade(0.6).incoming).toBeGreaterThan(0);
  });

  it("pairs each assistant response with the workspace visible at that moment", () => {
    const events = [
      event("0", "user.message", { text: "Start the workflow" }),
      event("1", "agent.message", { text: "First response" }),
      event("2", "user.message", { text: "Show the schedule" }),
      event("2", "workspace.panel.opened", {
        command: {
          type: "open",
          panel: {
            id: "40000000-0000-4000-8000-000000000001",
            component_id: "calendar",
            title: "Schedule",
            resource_uri: "course://schedule",
            props: {},
            state: {},
          },
        },
      }),
      event("3", "agent.message", { text: "Second response" }),
      event("4", "workspace.panel.closed", {
        command: {
          type: "close",
          panel_id: "40000000-0000-4000-8000-000000000001",
        },
      }),
      event("5", "agent.message", { text: "Third response" }),
    ];

    const moments = projectConversationTimeline(events);

    expect(moments.map(({ response }) => response)).toEqual([
      "First response",
      "Second response",
      "Third response",
    ]);
    expect(moments.map(({ userMessage }) => userMessage)).toEqual([
      "Start the workflow",
      "Show the schedule",
      undefined,
    ]);
    expect(moments[0]?.workspace.panels).toHaveLength(0);
    expect(moments[1]?.workspace.panels[0]?.title).toBe("Schedule");
    expect(moments[2]?.workspace.panels).toHaveLength(0);
    expect(momentAtOffset(moments, 1)?.response).toBe("Second response");
  });

  it("keeps only student-visible text from platform message context", () => {
    expect(
      visibleUserMessage(
        "Use this image\n\n" +
          "[Temporary upload: portrait.png; upload_id: private-id; media_type: image/png]",
      ),
    ).toBe("Use this image");
    expect(
      visibleUserMessage(
        "Internal action context\n<user_request>\nHelp me draft a reply\n</user_request>\nMore context",
      ),
    ).toBe("Help me draft a reply");
  });

  it("offers accessible movement backward and forward through moments", () => {
    const onOffsetChange = vi.fn();
    const moments = projectConversationTimeline([
      event("1", "agent.message", { text: "First" }),
      event("2", "agent.message", { text: "Second" }),
    ]);
    const { container, rerender } = render(
      <ConversationTimeline
        moments={moments}
        offset={0}
        onOffsetChange={onOffsetChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Go to an older assistant response" }));
    expect(onOffsetChange).toHaveBeenCalledWith(1);
    expect(container.querySelector(".conversation-timeline")).toHaveAttribute("data-active", "false");
    expect(
      screen.getByRole("button", { name: "Go to a newer assistant response" }),
    ).toBeDisabled();

    rerender(
      <ConversationTimeline moments={moments} offset={1} onOffsetChange={onOffsetChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Return to current response" }));
    expect(onOffsetChange).toHaveBeenCalledWith(0);
  });

  it("shows the scrub destination once the transition passes halfway", () => {
    const moments = projectConversationTimeline([
      event("0", "user.message", { text: "How do I start?" }),
      event("1", "agent.message", { text: "Start with the syllabus." }),
      event("2", "agent.message", { text: "Here is your plan." }),
    ]);
    const onOffsetChange = vi.fn();
    const { container, rerender } = render(
      <ConversationTimeline moments={moments} offset={0} previewOffset={1} progress={0.4} onOffsetChange={onOffsetChange} />,
    );
    expect(container.querySelector(".conversation-timeline")).toHaveAttribute("data-active", "true");
    expect(container.querySelector(".conversation-timeline")).toHaveAttribute("data-scrubbing", "true");
    expect(container.querySelector(".timeline-pager")).toHaveAttribute("aria-description", "Moment 2 of 2");
    expect(container.querySelector(".timeline-pager")).not.toHaveTextContent(/\d/);
    expect(container.querySelector(".timeline-pager-markers")?.children).toHaveLength(3);
    expect(container.querySelector(".timeline-pager-position")).toHaveStyle({ transform: "translate3d(9px, -50%, 0)" });

    rerender(
      <ConversationTimeline moments={moments} offset={0} previewOffset={1} progress={0.6} onOffsetChange={onOffsetChange} />,
    );
    expect(container.querySelector(".timeline-pager")).toHaveAttribute("aria-description", "Moment 1 of 2");
    expect(container.querySelector(".timeline-pager-position")).toHaveStyle({ transform: "translate3d(6px, -50%, 0)" });
  });

  it("keeps the visual pager compact across a long conversation", () => {
    const moments = projectConversationTimeline(
      Array.from({ length: 30 }, (_, index) =>
        event(String(index), "agent.message", { text: `Response ${index}` }),
      ),
    );
    const { container, rerender } = render(
      <ConversationTimeline moments={moments} offset={0} onOffsetChange={vi.fn()} />,
    );
    expect(container.querySelectorAll(".timeline-pager-marker")).toHaveLength(11);
    expect(container.querySelector(".timeline-pager-position")).toHaveStyle({ transform: "translate3d(150px, -50%, 0)" });

    rerender(<ConversationTimeline moments={moments} offset={29} onOffsetChange={vi.fn()} />);
    expect(container.querySelector(".timeline-pager")).toHaveAttribute("aria-description", "Moment 1 of 30");
    expect(container.querySelector(".timeline-pager-position")).toHaveStyle({ transform: "translate3d(0px, -50%, 0)" });
  });
});
