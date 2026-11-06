import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Workspace } from "./Workspace.js";

describe("Workspace", () => {
  it("shows private weekly feedback beneath the matching assignment", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        assignment_id: "week-3",
        feedback: {
          week: 3,
          date: "2026-10-17",
          reviewer: "Course TA",
          feedback: "Comments:\n\nPrivate Week 3 note\n\nGrading Checklist:\n✓ Code link\nx   Agent architecture",
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <Workspace
        conversationId="20000000-0000-4000-8000-000000000001"
        onBrowserActivate={vi.fn(async () => undefined)}
        onBrowserResize={vi.fn(async () => undefined)}
        onBrowserScroll={vi.fn(async () => undefined)}
        onCloseWorkspace={vi.fn(async () => undefined)}
        onInteraction={vi.fn(async () => undefined)}
        onPanelAction={vi.fn(async () => undefined)}
        state={{
          focusedPanelId: "40000000-0000-4000-8000-000000000004",
          panels: [{
            id: "40000000-0000-4000-8000-000000000004",
            componentId: "draft-document",
            resourceUri: "course://assignment/week-3",
            props: { title: "Week 3 Build", content: "# Week 3 Build\n\nBuild it." },
            state: { document_kind: "course-assignment-view", assignment_id: "week-3" },
          }],
        }}
      />,
    );

    const note = await screen.findByText("Private Week 3 note");
    const assignment = screen.getByRole("heading", { name: "Week 3 Build" });
    expect(assignment.compareDocumentPosition(note)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(screen.getByRole("heading", { name: "Weekly build feedback" })).toBeTruthy();
    const comments = screen.getByRole("region", { name: "TA comments section" });
    const checklist = screen.getByRole("region", { name: "Grading checklist" });
    expect(within(comments).getByText("Private Week 3 note")).toBeTruthy();
    expect(within(comments).queryByText("Code link")).toBeNull();
    expect(within(checklist).getByText("Code link").closest("li")?.dataset.status).toBe("met");
    expect(within(checklist).getByText("Agent architecture").closest("li")?.dataset.status).toBe("unmet");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/grades/mine/assignments/week-3",
      expect.objectContaining({ credentials: "include" }),
    );
    vi.unstubAllGlobals();
  });

  it("shows formatted weekly feedback below the grading policy and links to assignments", async () => {
    const onOpenAssignment = vi.fn();
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/v1/grades/mine") {
        return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ assignments: [
              { assignment_id: "week-2", title: "Week 2 Build", has_feedback: false },
              { assignment_id: "week-3", title: "Week 3 Build", has_feedback: true },
            ] }),
        });
      }
      if (url === "/api/v1/grades/mine/assignments/week-3") {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            assignment_id: "week-3",
            feedback: {
              week: 3,
              date: "2026-10-17",
              reviewer: "Course TA",
              feedback: "Comments:\n\nPrivate Week 3 note\n\nGrading Checklist:\n✓ Code link",
            },
          }),
        });
      }
      return Promise.resolve({
            ok: true,
            status: 200,
            headers: new Headers({ "content-type": "text/markdown" }),
            body: null,
            arrayBuffer: async () => new TextEncoder().encode(
              "# Syllabus\n\n## Assignments and Evaluation\n\nWeekly builds are graded.",
            ).buffer,
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <Workspace
        conversationId="20000000-0000-4000-8000-000000000001"
        onBrowserActivate={vi.fn(async () => undefined)}
        onBrowserResize={vi.fn(async () => undefined)}
        onBrowserScroll={vi.fn(async () => undefined)}
        onCloseWorkspace={vi.fn(async () => undefined)}
        onInteraction={vi.fn(async () => undefined)}
        onOpenAssignment={onOpenAssignment}
        onPanelAction={vi.fn(async () => undefined)}
        state={{
          focusedPanelId: "40000000-0000-4000-8000-000000000005",
          panels: [{
            id: "40000000-0000-4000-8000-000000000005",
            componentId: "document-viewer",
            resourceUri: "course://syllabus",
            props: { find_text: "Assignments and Evaluation" },
            state: { document_kind: "grading-overview" },
          }],
        }}
      />,
    );

    const note = await screen.findByText("Private Week 3 note");
    const policy = screen.getByText("Weekly builds are graded.");
    expect(policy.compareDocumentPosition(note)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    const card = screen.getByRole("article", { name: "Week 3 Build feedback" });
    expect(within(card).getByRole("region", { name: "TA comments section" })).toBeTruthy();
    expect(within(card).getByRole("region", { name: "Grading checklist" })).toBeTruthy();
    expect(screen.getByRole("article", { name: "Week 2 Build feedback" })).toHaveTextContent(
      "No TA feedback has been posted",
    );
    const link = within(card).getByRole("button", { name: /Open assignment/ });
    fireEvent.click(link);
    expect(onOpenAssignment).toHaveBeenCalledWith("week-3");
    vi.unstubAllGlobals();
  });

  it("shows a progress review after the due date in an open assignment", async () => {
    const onCheckAssignment = vi.fn();

    render(
      <Workspace
        browserControlsReady
        conversationId="20000000-0000-4000-8000-000000000001"
        onBrowserActivate={vi.fn(async () => undefined)}
        onBrowserResize={vi.fn(async () => undefined)}
        onBrowserScroll={vi.fn(async () => undefined)}
        onCheckAssignment={onCheckAssignment}
        onCloseWorkspace={vi.fn(async () => undefined)}
        onInteraction={vi.fn()}
        onPanelAction={vi.fn(async () => undefined)}
        onSubmitApplication={vi.fn()}
        state={{
          focusedPanelId: "40000000-0000-4000-8000-000000000004",
          panels: [
            {
              id: "40000000-0000-4000-8000-000000000004",
              componentId: "draft-document",
              resourceUri: "course://assignment/assignment-one",
              props: {
                title: "Assignment one",
                description: "Due Monday, October 5, 2026 · 11:59 PM",
                content: "# Assignment one\n\nBuild a thing.",
              },
              state: {
                document_kind: "course-assignment-view",
                assignment_id: "assignment-one",
              },
            },
          ],
        }}
      />,
    );

    const deadline = screen.getByText("Due Monday, October 5, 2026 · 11:59 PM");
    const check = screen.getByRole("button", { name: "Review my progress" });
    expect(deadline.compareDocumentPosition(check)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(screen.getAllByRole("heading", { name: "Assignment one" })).toHaveLength(1);
    fireEvent.click(check);
    expect(onCheckAssignment).toHaveBeenCalledWith(
      "course://assignment/assignment-one",
    );
  });

  it("centers an accessible loading bar with resource download progress", async () => {
    const read = vi
      .fn()
      .mockResolvedValueOnce({ done: false, value: new Uint8Array([37, 80]) })
      .mockImplementation(() => new Promise(() => undefined));
    const fetchRequest = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({
          "content-length": "4",
          "content-type": "application/pdf",
        }),
        body: { getReader: () => ({ read }) },
      } as unknown as Response);
    const view = render(
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
          focusedPanelId: "40000000-0000-4000-8000-000000000004",
          panels: [
            {
              id: "40000000-0000-4000-8000-000000000004",
              componentId: "document-viewer",
              resourceUri: "course://slides/week-01",
              props: {},
              state: {},
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("Opening resource…")).toBeVisible();
    const progressbar = screen.getByRole("progressbar", { name: "Opening resource" });
    expect(progressbar).toBeVisible();
    await waitFor(() => expect(progressbar).toHaveAttribute("aria-valuenow", "50"));
    expect(screen.getByText("50%")).toBeVisible();

    view.unmount();
    fetchRequest.mockRestore();
  });

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
