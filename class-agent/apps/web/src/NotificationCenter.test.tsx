import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NotificationCenter } from "./NotificationCenter.js";

const data = {
  generated_at: "2026-09-05T12:00:00Z",
  unread_count: 1,
  items: [
    {
      id: "10000000-0000-4000-8000-000000000001",
      section: "notifications" as const,
      kind: "course_update" as const,
      state: "unread" as const,
      title: "Assignment one released",
      detail: "The brief is now available.",
      timestamp: "2026-09-05T10:00:00Z",
      due_at: null,
      action_label: "Review with agent",
      action_prompt: "Review assignment one.",
      unread: true,
      dismissible: true,
      sender: null,
    },
    {
      id: "10000000-0000-4000-8000-000000000002",
      section: "communications" as const,
      kind: "pending_message" as const,
      state: "pending" as const,
      title: "Model choice",
      detail: "May I use a local model?",
      timestamp: "2026-09-04T10:00:00Z",
      due_at: null,
      action_label: "Check status",
      action_prompt: "Check my question.",
      unread: false,
      dismissible: false,
      sender: null,
    },
    {
      id: "10000000-0000-4000-8000-000000000004",
      section: "communications" as const,
      kind: "staff_reply" as const,
      state: "responded" as const,
      title: "Extension request",
      detail: "A one-day extension is fine.",
      timestamp: "2026-09-05T11:30:00Z",
      due_at: null,
      action_label: "Discuss response",
      action_prompt: "Help me understand the response.",
      unread: true,
      dismissible: true,
      sender: {
        first_name: "Chitralekha",
        resource_uri: "course://instructors",
        image_asset_id: "chitralekha_gupta_portrait",
      },
    },
    {
      id: "10000000-0000-4000-8000-000000000003",
      section: "upcoming" as const,
      kind: "assignment_deadline" as const,
      state: "upcoming" as const,
      title: "Assignment one",
      detail: "Assignment deadline",
      timestamp: null,
      due_at: "2026-09-17T12:00:00Z",
      action_label: "Plan with agent",
      action_prompt: "Plan assignment one.",
      unread: false,
      dismissible: false,
      sender: null,
    },
    {
      id: "10000000-0000-4000-8000-000000000005",
      section: "communications" as const,
      kind: "instructor_message" as const,
      state: "unread" as const,
      title: "Studio reminder",
      detail: "Bring your prototype to class.",
      timestamp: "2026-09-05T11:45:00Z",
      due_at: null,
      action_label: "Discuss message",
      action_prompt: "Help me respond to this message.",
      unread: true,
      dismissible: true,
      sender: {
        first_name: "Maya",
        resource_uri: null,
        image_asset_id: null,
      },
    },
  ],
};

describe("NotificationCenter", () => {
  it("renders updates first with communication and upcoming card groups", () => {
    const onAction = vi.fn();
    render(
      <NotificationCenter
        busy={false}
        data={data}
        historyExpanded={false}
        onAction={onAction}
        onHistoryExpandedChange={vi.fn()}
        onMarkRead={vi.fn()}
      />,
    );

    const center = screen.getByRole("complementary", { name: "Notification center" });
    const lists = within(center).getAllByRole("list");
    expect(lists.map((list) => list.getAttribute("aria-label"))).toEqual([
      "Updates",
      "Communications",
      "Upcoming",
    ]);
    expect(screen.getByRole("heading", { name: "Updates" })).toBeVisible();
    expect(
      screen.getByText(
        new Intl.RelativeTimeFormat(undefined, {
          numeric: "auto",
          style: "short",
        }).format(-2, "hour"),
      ),
    ).toBeVisible();
    expect(screen.getByText("Assignment one released")).toBeVisible();
    expect(screen.getByText("May I use a local model?")).toBeVisible();
    expect(center.querySelector(".notification-card-portrait img")).toHaveAttribute(
      "src",
      "/api/v1/course/resources/asset?uri=course%3A%2F%2Finstructors&asset_id=chitralekha_gupta_portrait",
    );
    expect(center.querySelector(".notification-card-portrait img")).toHaveAttribute(
      "alt",
      "",
    );
    expect(screen.getByText("Chitralekha")).toHaveClass("notification-card-sender");
    expect(screen.getByText("Maya")).toHaveClass("notification-card-sender");
    expect(screen.getByText("Discuss response")).toHaveClass(
      "notification-card-action",
    );
    expect(screen.getByText(/Due in 12 days/)).toBeVisible();
    expect(
      Array.from(center.querySelectorAll("[data-notification-icon]")).map((icon) =>
        icon.getAttribute("data-notification-icon"),
      ),
    ).toEqual([
      "course_update",
      "pending_message",
      "instructor_message",
      "assignment_deadline",
    ]);
    const assignmentCard = screen
      .getByRole("button", { name: "Plan with agent: Assignment one" })
      .closest("article");
    expect(assignmentCard).toHaveClass("notification-assignment-card");
    expect(
      assignmentCard?.querySelector(".notification-assignment-date"),
    ).toBeInTheDocument();

    const scrollSurface = center.querySelector(".notification-center-scroll");
    expect(center).toHaveAttribute("data-scrolled", "false");
    fireEvent.scroll(scrollSurface!, { target: { scrollTop: 24 } });
    expect(center).toHaveAttribute("data-scrolled", "true");
    fireEvent.scroll(scrollSurface!, { target: { scrollTop: 0 } });
    expect(center).toHaveAttribute("data-scrolled", "false");

    fireEvent.click(screen.getByRole("button", { name: "Plan with agent: Assignment one" }));
    expect(onAction).toHaveBeenCalledWith(data.items[3]);
    expect(center).toBeVisible();
  });

  it("does not reserve a surface when there are no items", () => {
    render(
      <NotificationCenter
        busy={false}
        data={{ ...data, unread_count: 0, items: [] }}
        historyExpanded={false}
        onAction={vi.fn()}
        onHistoryExpandedChange={vi.fn()}
        onMarkRead={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("complementary", { name: "Notification center" }),
    ).toBeNull();
  });

  it("uses the close control without triggering the card action", () => {
    const onAction = vi.fn();
    const onMarkRead = vi.fn();
    render(
      <NotificationCenter
        busy={false}
        data={{ ...data, items: [data.items[0]!] }}
        historyExpanded={false}
        onAction={onAction}
        onHistoryExpandedChange={vi.fn()}
        onMarkRead={onMarkRead}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Mark “Assignment one released” read",
      }),
    );

    expect(onMarkRead).toHaveBeenCalledWith(data.items[0]!.id);
    expect(onAction).not.toHaveBeenCalled();
  });

  it("formats the bounded countdown without fractional days", () => {
    render(
      <NotificationCenter
        busy={false}
        data={{
          ...data,
          items: [
            {
              ...data.items[3]!,
              due_at: "2026-09-06T11:59:00Z",
            },
          ],
        }}
        historyExpanded={false}
        onAction={vi.fn()}
        onHistoryExpandedChange={vi.fn()}
        onMarkRead={vi.fn()}
      />,
    );

    expect(screen.getByText("Due tomorrow")).toBeVisible();
  });

  it("reveals the newest three items in each category before expanding full history", () => {
    const update = data.items[0]!;
    const historyItems = [
      {
        ...update,
        id: "10000000-0000-4000-8000-000000000011",
        state: "read" as const,
        title: "Oldest update",
        timestamp: "2026-09-01T10:00:00Z",
        unread: false,
        dismissible: false,
      },
      {
        ...update,
        id: "10000000-0000-4000-8000-000000000012",
        state: "read" as const,
        title: "Middle update",
        timestamp: "2026-09-03T10:00:00Z",
        unread: false,
        dismissible: false,
      },
      update,
      {
        ...update,
        id: "10000000-0000-4000-8000-000000000013",
        state: "read" as const,
        title: "Earlier update",
        timestamp: "2026-09-02T10:00:00Z",
        unread: false,
        dismissible: false,
      },
      ...data.items.slice(1),
    ];
    const onHistoryExpandedChange = vi.fn();
    const view = render(
      <NotificationCenter
        busy={false}
        data={{ ...data, history_items: historyItems }}
        historyExpanded={false}
        onAction={vi.fn()}
        onHistoryExpandedChange={onHistoryExpandedChange}
        onMarkRead={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "See more" }));
    expect(onHistoryExpandedChange).toHaveBeenCalledWith(true);
    view.rerender(
      <NotificationCenter
        busy={false}
        data={{ ...data, history_items: historyItems }}
        historyExpanded
        onAction={vi.fn()}
        onHistoryExpandedChange={onHistoryExpandedChange}
        onMarkRead={vi.fn()}
      />,
    );

    const updates = screen.getByRole("list", { name: "Updates" });
    expect(within(updates).getAllByRole("listitem")).toHaveLength(3);
    expect(within(updates).getAllByRole("listitem")[0]).toHaveTextContent(
      "Assignment one released",
    );
    expect(screen.queryByText("Oldest update")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Show all updates" }),
    );
    expect(within(updates).getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByText("Oldest update")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Show newest 3 updates" }),
    ).toHaveAttribute("aria-expanded", "true");
  });
});
