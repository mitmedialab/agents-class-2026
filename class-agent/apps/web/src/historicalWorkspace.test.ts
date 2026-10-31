import { builtInComponentRegistry, emptyWorkspaceState } from "@class-agent/workspace";
import { describe, expect, it } from "vitest";

import { historicalInteraction, historicalPanelAction } from "./historicalWorkspace.js";

const panelId = "40000000-0000-4000-8000-000000000010";

describe("historical workspace exploration", () => {
  it("changes a projected panel locally without changing the source snapshot", () => {
    const snapshot = builtInComponentRegistry.apply(emptyWorkspaceState(), {
      type: "open",
      panel: {
        id: panelId,
        component_id: "calendar",
        props: { view: "agenda" },
        state: {},
      },
    });

    const explored = historicalInteraction(snapshot, panelId, "calendar.change_view", "month");
    expect(snapshot.panels[0]?.props.view).toBe("agenda");
    expect(explored.panels[0]?.props.view).toBe("month");
    expect(historicalPanelAction(explored, "close", panelId).panels).toHaveLength(0);
    expect(snapshot.panels).toHaveLength(1);
  });

  it("ignores unsupported or invalid local actions", () => {
    const snapshot = emptyWorkspaceState();
    expect(historicalInteraction(snapshot, panelId, "browser.click", "x")).toBe(snapshot);
    expect(historicalPanelAction(snapshot, "close", panelId)).toBe(snapshot);
  });
});
