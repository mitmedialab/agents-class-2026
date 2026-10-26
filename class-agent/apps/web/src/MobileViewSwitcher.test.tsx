import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MobileViewSwitcher } from "./MobileViewSwitcher.js";

describe("MobileViewSwitcher", () => {
  it("switches accessibly between Chat and Notifications", () => {
    const onViewChange = vi.fn();
    render(
      <MobileViewSwitcher
        activeView="chat"
        count={3}
        onViewChange={onViewChange}
        secondaryView="updates"
      />,
    );

    const group = screen.getByRole("group", { name: "Mobile view" });
    expect(within(group).getByRole("button", { name: "Chat" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const notifications = within(group).getByRole("button", {
      name: /Notifications/,
    });
    expect(notifications).toHaveAttribute("aria-pressed", "false");
    expect(notifications).toHaveAccessibleName("Notifications, 3 active items");

    fireEvent.click(notifications);
    expect(onViewChange).toHaveBeenCalledWith("updates");
  });

  it("switches between Chat and Workspace without a notification count", () => {
    const onViewChange = vi.fn();
    render(
      <MobileViewSwitcher
        activeView="workspace"
        onViewChange={onViewChange}
        secondaryView="workspace"
      />,
    );

    const group = screen.getByRole("group", { name: "Mobile view" });
    const workspace = within(group).getByRole("button", { name: "Workspace" });
    expect(workspace).toHaveAttribute("aria-pressed", "true");
    expect(workspace).toHaveAccessibleName("Workspace");

    fireEvent.click(within(group).getByRole("button", { name: "Chat" }));
    expect(onViewChange).toHaveBeenCalledWith("chat");
  });
});
