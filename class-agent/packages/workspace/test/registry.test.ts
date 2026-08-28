import { readFileSync } from "node:fs";

import Ajv2020Package from "ajv/dist/2020.js";
import addFormatsPackage from "ajv-formats";
import type { Ajv2020 as Ajv2020Type } from "ajv/dist/2020.js";
import type { FormatsPlugin } from "ajv-formats";
import { describe, expect, it } from "vitest";

import {
  BUILT_IN_COMPONENT_MANIFESTS,
  ComponentRegistry,
  WorkspaceValidationError,
  emptyWorkspaceState,
  projectWorkspaceEvents,
} from "../src/index.js";

const Ajv2020 = Ajv2020Package as unknown as typeof Ajv2020Type;
const addFormats = addFormatsPackage as unknown as FormatsPlugin;
const panelId = "40000000-0000-4000-8000-000000000001";

function openCalendar() {
  return {
    type: "open",
    panel: {
      id: panelId,
      component_id: "calendar",
      title: "Course schedule",
      resource_uri: "course://schedule",
      props: { view: "agenda", focus_date: "2026-09-20" },
      state: {},
    },
  };
}

describe("component registry", () => {
  it("matches the published registry and versioned JSON Schema", () => {
    const registryPath = new URL(
      "../../../shared/registry/components.json",
      import.meta.url,
    );
    const schemaPath = new URL(
      "../../../shared/schemas/v1/workspace.schema.json",
      import.meta.url,
    );
    const published = JSON.parse(readFileSync(registryPath, "utf8")) as {
      components: unknown[];
    };
    const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as {
      $id: string;
      [key: string]: unknown;
    };
    const ajv = new Ajv2020({ allErrors: true, strict: true });
    addFormats(ajv);
    ajv.addSchema(schema);
    const validate = ajv.getSchema(`${schema.$id}#/$defs/ComponentRegistry`);

    expect(validate?.(published), JSON.stringify(validate?.errors)).toBe(true);
    expect(published.components).toEqual(
      BUILT_IN_COMPONENT_MANIFESTS.map((manifest) => ({
        id: manifest.id,
        version: manifest.version,
        title: manifest.title,
        description: manifest.description,
        props_schema: manifest.propsSchema,
        supported_operations: manifest.supportedOperations,
        default_size: manifest.defaultSize,
      })),
    );
  });

  it("applies valid open, update, focus, and close commands", () => {
    const registry = new ComponentRegistry(BUILT_IN_COMPONENT_MANIFESTS);
    const opened = registry.apply(emptyWorkspaceState(), openCalendar());
    expect(opened.focusedPanelId).toBe(panelId);
    expect(opened.panels[0]?.resourceUri).toBe("course://schedule");

    const updated = registry.apply(opened, {
      type: "update",
      panel_id: panelId,
      props: { view: "month" },
    });
    expect(updated.panels[0]?.props).toEqual({
      view: "month",
      focus_date: "2026-09-20",
    });
    expect(registry.apply(updated, { type: "focus", panel_id: panelId })).toEqual(
      updated,
    );
    expect(registry.apply(updated, { type: "close", panel_id: panelId })).toEqual({
      panels: [],
    });
  });

  it("replaces the prior surface when the workspace focus changes", () => {
    const registry = new ComponentRegistry(BUILT_IN_COMPONENT_MANIFESTS);
    const first = registry.apply(emptyWorkspaceState(), openCalendar());
    const nextId = "40000000-0000-4000-8000-000000000012";
    const second = registry.apply(first, {
      type: "open",
      panel: {
        ...openCalendar().panel,
        id: nextId,
        title: "Review dates",
      },
    });

    expect(second.panels.map((panel) => panel.id)).toEqual([nextId]);
    expect(second.focusedPanelId).toBe(nextId);

    const focused = registry.apply(
      {
        panels: [first.panels[0]!, second.panels[0]!],
        focusedPanelId: nextId,
      },
      { type: "focus", panel_id: panelId },
    );
    expect(focused.panels.map((panel) => panel.id)).toEqual([panelId]);
  });

  it("rejects unknown components, bad props, and unsupported operations", () => {
    const registry = new ComponentRegistry(BUILT_IN_COMPONENT_MANIFESTS);
    expect(() =>
      registry.apply(emptyWorkspaceState(), {
        ...openCalendar(),
        panel: { ...openCalendar().panel, component_id: "invented-ui" },
      }),
    ).toThrow("unknown component");
    expect(() =>
      registry.apply(emptyWorkspaceState(), {
        ...openCalendar(),
        panel: { ...openCalendar().panel, props: { view: "timeline" } },
      }),
    ).toThrow("invalid props");
    expect(
      registry.apply(emptyWorkspaceState(), {
        type: "open",
        panel: {
          id: "40000000-0000-4000-8000-000000000004",
          component_id: "draft-document",
          props: {
            title: "Project proposal",
            content: "# Proposal\n\nAn evolving project draft.",
            status: "draft",
          },
          state: {},
        },
      }).panels[0]?.props.content,
    ).toBe("# Proposal\n\nAn evolving project draft.");
    expect(() =>
      registry.apply(emptyWorkspaceState(), {
        type: "open",
        panel: {
          id: "40000000-0000-4000-8000-000000000003",
          component_id: "draft-document",
          props: {
            title: "Application",
            fields: [{ id: "name", label: "Name", status: "made-up" }],
          },
          state: {},
        },
      }),
    ).toThrow("invalid props");
    expect(() =>
      registry.apply(emptyWorkspaceState(), {
        type: "open",
        panel: {
          id: "40000000-0000-4000-8000-000000000002",
          component_id: "webpage-viewer",
          props: { url: "javascript:alert(1)" },
          state: {},
        },
      }),
    ).toThrow("invalid props");

    const calendarManifest = BUILT_IN_COMPONENT_MANIFESTS.find(
      (manifest) => manifest.id === "calendar",
    )!;
    const openOnly = new ComponentRegistry([
      { ...calendarManifest, supportedOperations: ["open"] },
    ]);
    const state = openOnly.apply(emptyWorkspaceState(), openCalendar());
    expect(() =>
      openOnly.apply(state, { type: "close", panel_id: panelId }),
    ).toThrow("does not support close");
  });

  it("projects canonical workspace events deterministically", () => {
    const state = projectWorkspaceEvents([
      { type: "user.message", payload: {} },
      { type: "workspace.panel.opened", payload: { command: openCalendar() } },
      {
        type: "workspace.panel.updated",
        payload: {
          command: { type: "update", panel_id: panelId, props: { view: "month" } },
        },
      },
    ]);
    expect(state.panels).toHaveLength(1);
    expect(state.panels[0]?.props.view).toBe("month");
  });

  it("validates visual compositions as safe single-parent component trees", () => {
    const registry = new ComponentRegistry(BUILT_IN_COMPONENT_MANIFESTS);
    const visual = {
      type: "open",
      panel: {
        id: "40000000-0000-4000-8000-000000000009",
        component_id: "visual-composition",
        props: {
          root_id: "profile",
          elements: [
            {
              id: "profile",
              type: "group",
              children: ["photo", "name", "bio"],
              surface: "raised",
              padding: "large",
            },
            {
              id: "photo",
              type: "image",
              url: "https://example.com/photo.jpg",
              alt: "Portrait",
              presentation: "banner",
              radius: "round",
            },
            { id: "name", type: "heading", text: "Ada Example" },
            { id: "bio", type: "text", text: "Researcher" },
          ],
        },
        state: {},
      },
    };

    expect(registry.apply(emptyWorkspaceState(), visual).panels).toHaveLength(1);

    expect(
      registry.apply(emptyWorkspaceState(), {
        ...visual,
        panel: {
          ...visual.panel,
          resource_uri: "course://instructors",
          props: {
            ...visual.panel.props,
            elements: visual.panel.props.elements.map((element) => {
              if (element.id !== "photo") return element;
              const { url: _url, ...withoutUrl } = element;
              return { ...withoutUrl, asset_id: "pattie_maes_portrait" };
            }),
          },
        },
      }).panels,
    ).toHaveLength(1);

    expect(() =>
      registry.apply(emptyWorkspaceState(), {
        ...visual,
        panel: {
          ...visual.panel,
          props: {
            ...visual.panel.props,
            elements: visual.panel.props.elements.map((element) =>
              element.id === "photo"
                ? { ...element, asset_id: "pattie_maes_portrait" }
                : element,
            ),
          },
        },
      }),
    ).toThrow("invalid props");

    expect(() =>
      registry.apply(emptyWorkspaceState(), {
        ...visual,
        panel: {
          ...visual.panel,
          props: {
            root_id: "root",
            elements: [
              { id: "root", type: "text", text: "Visible" },
              { id: "orphan", type: "text", text: "Hidden" },
            ],
          },
        },
      }),
    ).toThrow("unreachable");
  });

  it("validates bounded chart data inside visual compositions", () => {
    const registry = new ComponentRegistry(BUILT_IN_COMPONENT_MANIFESTS);
    const visual = {
      type: "open",
      panel: {
        id: "40000000-0000-4000-8000-000000000010",
        component_id: "visual-composition",
        props: {
          root_id: "trend",
          elements: [
            {
              id: "trend",
              type: "chart",
              title: "Weekly participation",
              chart_type: "area",
              labels: ["Week 1", "Week 2", "Week 3"],
              series: [
                {
                  label: "Students",
                  values: [12, 18, 24],
                  tone: "success",
                  tones: ["coral", "secondary", "violet"],
                },
              ],
              value_suffix: " students",
            },
          ],
        },
        state: {},
      },
    };

    expect(registry.apply(emptyWorkspaceState(), visual).panels).toHaveLength(1);
    expect(() =>
      registry.apply(emptyWorkspaceState(), {
        ...visual,
        panel: {
          ...visual.panel,
          props: {
            ...visual.panel.props,
            elements: [
              {
                ...visual.panel.props.elements[0],
                series: [{ label: "Students", values: [12, 18] }],
              },
            ],
          },
        },
      }),
    ).toThrow("chart series values must match chart labels");

    expect(() =>
      registry.apply(emptyWorkspaceState(), {
        ...visual,
        panel: {
          ...visual.panel,
          props: {
            ...visual.panel.props,
            elements: [
              {
                ...visual.panel.props.elements[0],
                series: [
                  {
                    label: "Students",
                    values: [12, 18, 24],
                    tones: ["coral", "violet"],
                  },
                ],
              },
            ],
          },
        },
      }),
    ).toThrow("chart point tones must match chart labels");
  });

  it("rejects invented command fields before state changes", () => {
    const registry = new ComponentRegistry(BUILT_IN_COMPONENT_MANIFESTS);
    expect(() =>
      registry.apply(emptyWorkspaceState(), { ...openCalendar(), script: "alert(1)" }),
    ).toThrow(WorkspaceValidationError);
  });
});
