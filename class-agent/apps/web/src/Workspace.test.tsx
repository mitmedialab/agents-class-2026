import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Workspace } from "./Workspace.js";

describe("Workspace", () => {
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

  it("resolves a protected applicant URI through the instructor photo route", () => {
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
              props: {
                root_id: "photo",
                elements: [
                  {
                    id: "photo",
                    type: "image",
                    url: "applicant://50000000-0000-4000-8000-000000000002/photo",
                    alt: "Submitted application image",
                    presentation: "card",
                  },
                ],
              },
              state: {},
            },
          ],
        }}
      />,
    );

    expect(screen.getByAltText("Submitted application image")).toHaveAttribute(
      "src",
      "/api/v1/instructor/applications/50000000-0000-4000-8000-000000000002/photo",
    );
  });

  it("waits for the latest draft edit before submitting an application", async () => {
    let finishSave = () => {};
    const onInteraction = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishSave = resolve;
        }),
    );
    const onSubmitApplication = vi.fn();

    render(
      <Workspace
        conversationId="20000000-0000-4000-8000-000000000001"
        onBrowserActivate={vi.fn(async () => undefined)}
        onBrowserResize={vi.fn(async () => undefined)}
        onBrowserScroll={vi.fn(async () => undefined)}
        onCloseWorkspace={vi.fn(async () => undefined)}
        onInteraction={onInteraction}
        onPanelAction={vi.fn(async () => undefined)}
        onSubmitApplication={onSubmitApplication}
        state={{
          focusedPanelId: "40000000-0000-4000-8000-000000000003",
          panels: [
            {
              id: "40000000-0000-4000-8000-000000000003",
              componentId: "draft-document",
              resourceUri: "course://application",
              props: {
                title: "Course Application Draft",
                fields: [
                  {
                    id: "name",
                    label: "Name",
                    status: "confirmed",
                    value: "Ada Example",
                  },
                ],
              },
              state: {},
            },
          ],
        }}
      />,
    );

    const name = screen.getByRole("textbox", { name: "Name" });
    fireEvent.change(name, { target: { value: "Ada Lovelace" } });
    fireEvent.blur(name);
    fireEvent.click(screen.getByRole("button", { name: "Submit application" }));

    expect(onInteraction).toHaveBeenCalledWith(
      "40000000-0000-4000-8000-000000000003",
      "draft.change",
      { field_id: "name", value: "Ada Lovelace" },
    );
    expect(onSubmitApplication).not.toHaveBeenCalled();

    finishSave();
    await waitFor(() => expect(onSubmitApplication).toHaveBeenCalledOnce());
  });
});
