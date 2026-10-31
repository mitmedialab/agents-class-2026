import {
  builtInComponentRegistry,
  type JsonValue,
  type WorkspaceState,
} from "@class-agent/workspace";

/** Exploratory changes to a past workspace never append canonical conversation events. */
export function historicalPanelAction(
  state: WorkspaceState,
  action: "focus" | "close",
  panelId: string,
): WorkspaceState {
  try {
    return builtInComponentRegistry.apply(state, { type: action, panel_id: panelId });
  } catch {
    return state;
  }
}

export function historicalInteraction(
  state: WorkspaceState,
  panelId: string,
  action: string,
  value: JsonValue,
): WorkspaceState {
  const panel = state.panels.find((candidate) => candidate.id === panelId);
  if (!panel) return state;

  let props: Record<string, JsonValue> | null = null;
  if (action === "calendar.select_event" && typeof value === "string") {
    props = { selected_event_id: value };
  } else if (action === "calendar.change_view" && (value === "month" || value === "agenda")) {
    props = { view: value };
  } else if (action === "document.change_page" && typeof value === "number" && value >= 1) {
    props = { page: value };
  } else if (action === "document.find_text" && typeof value === "string") {
    props = { find_text: value };
  } else if (action === "page_cards.select" && typeof value === "string") {
    props = { selected_id: value };
  } else if (
    action === "draft.change" &&
    value !== null && typeof value === "object" && !Array.isArray(value) &&
    typeof value.field_id === "string" && typeof value.value === "string" &&
    Array.isArray(panel.props.fields)
  ) {
    props = {
      fields: panel.props.fields.map((field) =>
        field !== null && typeof field === "object" && !Array.isArray(field) &&
        field.id === value.field_id
          ? { ...field, value: String(value.value) }
          : field,
      ),
    };
  } else if (
    action === "visual.change" &&
    value !== null && typeof value === "object" && !Array.isArray(value) &&
    typeof value.element_id === "string" && typeof value.value === "string" &&
    Array.isArray(panel.props.elements)
  ) {
    props = {
      elements: panel.props.elements.map((element) =>
        element !== null && typeof element === "object" && !Array.isArray(element) &&
        element.id === value.element_id &&
        (element.type === "input" || element.type === "textarea")
          ? { ...element, value: String(value.value) }
          : element,
      ),
    };
  }
  if (!props) return state;
  try {
    return builtInComponentRegistry.apply(state, { type: "update", panel_id: panelId, props });
  } catch {
    return state;
  }
}
