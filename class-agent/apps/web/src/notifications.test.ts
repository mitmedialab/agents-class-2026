import { describe, expect, it } from "vitest";
import type { NotificationCenterData, NotificationCenterItem } from "./api.js";
import { mergeNotificationCenterUpdates } from "./notifications.js";

function item(
  id: string,
  title: string,
  unread = true,
): NotificationCenterItem {
  return {
    id,
    section: "notifications",
    kind: "course_update",
    state: unread ? "unread" : "read",
    title,
    detail: `${title} detail`,
    timestamp: "2026-09-16T06:00:00Z",
    due_at: null,
    action_label: "Discuss update",
    action_prompt: `Discuss ${title}`,
    unread,
    dismissible: unread,
    sender: null,
  };
}

describe("mergeNotificationCenterUpdates", () => {
  it("adds and updates polled items without removing the current snapshot", () => {
    const current: NotificationCenterData = {
      generated_at: "2026-09-16T06:00:00Z",
      unread_count: 2,
      items: [item("existing", "Earlier update"), item("retained", "Retained update")],
    };
    const incoming: NotificationCenterData = {
      generated_at: "2026-09-16T06:01:00Z",
      unread_count: 1,
      items: [item("new", "New update"), item("existing", "Updated title", false)],
    };

    expect(mergeNotificationCenterUpdates(current, incoming)).toEqual({
      generated_at: "2026-09-16T06:01:00Z",
      unread_count: 2,
      items: [
        item("new", "New update"),
        item("existing", "Updated title", false),
        item("retained", "Retained update"),
      ],
    });
  });
});
