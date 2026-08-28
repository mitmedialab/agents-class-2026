import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Workspace } from "./Workspace.js";

describe("Workspace registered course assets", () => {
  it("resolves a registered image ID through the guarded course asset route", () => {
    render(
      <Workspace
        conversationId="20000000-0000-4000-8000-000000000001"
        onBrowserActivate={vi.fn(async () => undefined)}
        onBrowserResize={vi.fn(async () => undefined)}
        onBrowserScroll={vi.fn(async () => undefined)}
        onCloseWorkspace={vi.fn(async () => undefined)}
        onInteraction={vi.fn()}
        onPanelAction={vi.fn(async () => undefined)}
        onSubmitApplication={vi.fn()}
        state={{
          focusedPanelId: "40000000-0000-4000-8000-000000000001",
          panels: [
            {
              id: "40000000-0000-4000-8000-000000000001",
              componentId: "visual-composition",
              resourceUri: "course://instructors",
              props: {
                root_id: "portrait",
                elements: [
                  {
                    id: "portrait",
                    type: "image",
                    asset_id: "pattie_maes_portrait",
                    alt: "Portrait of Pattie Maes",
                    presentation: "avatar",
                  },
                ],
              },
              state: {},
            },
          ],
        }}
      />,
    );

    expect(screen.getByAltText("Portrait of Pattie Maes")).toHaveAttribute(
      "src",
      "/api/v1/course/resources/asset?uri=course%3A%2F%2Finstructors&asset_id=pattie_maes_portrait",
    );
  });
});
