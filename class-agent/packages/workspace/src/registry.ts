import { BUILT_IN_COMPONENT_MANIFESTS } from "./manifests.js";
import type {
  ComponentManifest,
  ComponentOperation,
  JsonObject,
  JsonValue,
  WorkspaceCommand,
  WorkspaceEventLike,
  WorkspacePanel,
  WorkspaceState,
} from "./types.js";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const COMPONENT_ID_PATTERN = /^[a-z][a-z0-9-]*$/;
const WORKSPACE_EVENT_TYPES = new Set([
  "workspace.panel.opened",
  "workspace.panel.updated",
  "workspace.panel.closed",
]);

export class WorkspaceValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WorkspaceValidationError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value))
  ) {
    return true;
  }
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function valuesEqual(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function validateFormat(format: unknown, value: string): boolean {
  if (format === "uuid") return UUID_PATTERN.test(value);
  if (format === "uri") {
    try {
      const parsed = new URL(value);
      return Boolean(parsed.protocol && parsed.hostname);
    } catch {
      return false;
    }
  }
  if (format === "date") {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(date.valueOf()) && date.toISOString().startsWith(value);
  }
  return true;
}

function schemaError(schema: JsonObject, value: unknown, path = "value"): string | undefined {
  if (Array.isArray(schema.enum) && !schema.enum.some((candidate) => valuesEqual(candidate, value))) {
    return `${path} is not an allowed value`;
  }
  if (schema.const !== undefined && !valuesEqual(schema.const, value)) {
    return `${path} does not match its required value`;
  }
  const type = schema.type;
  if (
    type === "object" ||
    (type === undefined &&
      isRecord(value) &&
      (isRecord(schema.properties) || Array.isArray(schema.required)))
  ) {
    if (!isRecord(value)) return `${path} must be an object`;
    const properties = isRecord(schema.properties) ? schema.properties : {};
    if (Array.isArray(schema.required)) {
      for (const key of schema.required) {
        if (typeof key === "string" && !(key in value)) return `${path}.${key} is required`;
      }
    }
    if (schema.additionalProperties === false) {
      const unknown = Object.keys(value).find((key) => !(key in properties));
      if (unknown) return `${path}.${unknown} is not allowed`;
    }
    for (const [key, childValue] of Object.entries(value)) {
      const childSchema = properties[key];
      if (isRecord(childSchema)) {
        const error = schemaError(childSchema as JsonObject, childValue, `${path}.${key}`);
        if (error) return error;
      }
    }
    if (isRecord(schema.dependentRequired)) {
      for (const [key, dependencies] of Object.entries(schema.dependentRequired)) {
        if (!(key in value) || !Array.isArray(dependencies)) continue;
        const missing = dependencies.find(
          (dependency) => typeof dependency === "string" && !(dependency in value),
        );
        if (typeof missing === "string") return `${path}.${missing} is required with ${key}`;
      }
    }
  } else if (type === "array") {
    if (!Array.isArray(value)) return `${path} must be an array`;
    if (typeof schema.minItems === "number" && value.length < schema.minItems) {
      return `${path} has too few items`;
    }
    if (typeof schema.maxItems === "number" && value.length > schema.maxItems) {
      return `${path} has too many items`;
    }
    if (schema.uniqueItems === true) {
      const encoded = value.map((item) => JSON.stringify(item));
      if (new Set(encoded).size !== encoded.length) return `${path} items must be unique`;
    }
    if (isRecord(schema.items)) {
      for (const [index, item] of value.entries()) {
        const error = schemaError(schema.items as JsonObject, item, `${path}[${index}]`);
        if (error) return error;
      }
    }
  } else if (type === "string") {
    if (typeof value !== "string") return `${path} must be a string`;
    if (typeof schema.minLength === "number" && value.length < schema.minLength) {
      return `${path} is too short`;
    }
    if (typeof schema.maxLength === "number" && value.length > schema.maxLength) {
      return `${path} is too long`;
    }
    if (typeof schema.pattern === "string" && !new RegExp(schema.pattern, "u").test(value)) {
      return `${path} has an invalid format`;
    }
    if (!validateFormat(schema.format, value)) return `${path} has an invalid format`;
  } else if (type === "integer") {
    if (typeof value !== "number" || !Number.isInteger(value)) return `${path} must be an integer`;
  } else if (type === "number") {
    if (typeof value !== "number" || !Number.isFinite(value)) return `${path} must be a number`;
  } else if (type === "boolean" && typeof value !== "boolean") {
    return `${path} must be a boolean`;
  }
  if (typeof value === "number") {
    if (typeof schema.minimum === "number" && value < schema.minimum) return `${path} is too small`;
    if (typeof schema.maximum === "number" && value > schema.maximum) return `${path} is too large`;
  }
  for (const keyword of ["allOf", "anyOf", "oneOf"] as const) {
    const branches = schema[keyword];
    if (!Array.isArray(branches)) continue;
    const passing = branches.filter(
      (branch) => isRecord(branch) && schemaError(branch as JsonObject, value, path) === undefined,
    ).length;
    if (keyword === "allOf" && passing !== branches.length) return `${path} is invalid`;
    if (keyword === "anyOf" && passing === 0) return `${path} is invalid`;
    if (keyword === "oneOf" && passing !== 1) return `${path} is invalid`;
  }
  return undefined;
}

function jsonObject(value: unknown, label: string): JsonObject {
  if (!isRecord(value) || !isJsonValue(value)) {
    throw new WorkspaceValidationError(`${label} must be a JSON object`);
  }
  return value as JsonObject;
}

function nonBlankString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new WorkspaceValidationError(`${label} must be non-blank text`);
  }
  return value;
}

function panelId(value: unknown): string {
  const id = nonBlankString(value, "panel id");
  if (!UUID_PATTERN.test(id)) {
    throw new WorkspaceValidationError("panel id must be a UUID");
  }
  return id;
}

function optionalString(value: unknown, label: string): string | undefined {
  if (value === undefined) return undefined;
  return nonBlankString(value, label);
}

function parsePanel(value: unknown): WorkspacePanel {
  if (!isRecord(value)) throw new WorkspaceValidationError("panel must be an object");
  if (
    !hasOnlyKeys(value, [
      "id",
      "component_id",
      "title",
      "resource_uri",
      "props",
      "state",
      "layout",
    ])
  ) {
    throw new WorkspaceValidationError("panel contains unknown fields");
  }
  const parsed: WorkspacePanel = {
    id: panelId(value.id),
    componentId: nonBlankString(value.component_id, "component id"),
    props: jsonObject(value.props, "panel props"),
    state: jsonObject(value.state, "panel state"),
  };
  const title = optionalString(value.title, "panel title");
  const resourceUri = optionalString(value.resource_uri, "resource URI");
  if (title !== undefined) parsed.title = title;
  if (resourceUri !== undefined) parsed.resourceUri = resourceUri;
  if (value.layout !== undefined) {
    if (!isRecord(value.layout) || !hasOnlyKeys(value.layout, ["width", "height"])) {
      throw new WorkspaceValidationError("panel layout is invalid");
    }
    const layout: { width?: number; height?: number } = {};
    for (const field of ["width", "height"] as const) {
      const dimension = value.layout[field];
      if (dimension !== undefined) {
        if (typeof dimension !== "number" || !Number.isFinite(dimension) || dimension <= 0) {
          throw new WorkspaceValidationError(`${field} must be positive`);
        }
        layout[field] = dimension;
      }
    }
    parsed.layout = layout;
  }
  return parsed;
}

export function parseWorkspaceCommand(value: unknown): WorkspaceCommand {
  if (!isRecord(value) || typeof value.type !== "string") {
    throw new WorkspaceValidationError("workspace command must be an object with a type");
  }
  if (value.type === "open") {
    if (!hasOnlyKeys(value, ["type", "panel"])) {
      throw new WorkspaceValidationError("open command contains unknown fields");
    }
    return { type: "open", panel: parsePanel(value.panel) };
  }
  if (value.type === "focus" || value.type === "close") {
    if (!hasOnlyKeys(value, ["type", "panel_id"])) {
      throw new WorkspaceValidationError(`${value.type} command contains unknown fields`);
    }
    return { type: value.type, panelId: panelId(value.panel_id) };
  }
  if (value.type === "update") {
    if (
      !hasOnlyKeys(value, [
        "type",
        "panel_id",
        "props",
        "state",
        "title",
        "resource_uri",
      ])
    ) {
      throw new WorkspaceValidationError("update command contains unknown fields");
    }
    const command: WorkspaceCommand = {
      type: "update",
      panelId: panelId(value.panel_id),
    };
    if (value.props !== undefined) command.props = jsonObject(value.props, "props");
    if (value.state !== undefined) command.state = jsonObject(value.state, "state");
    if (value.title !== undefined) {
      command.title = value.title === null ? null : nonBlankString(value.title, "title");
    }
    if (value.resource_uri !== undefined) {
      command.resourceUri =
        value.resource_uri === null
          ? null
          : nonBlankString(value.resource_uri, "resource URI");
    }
    if (
      command.props === undefined &&
      command.state === undefined &&
      command.title === undefined &&
      command.resourceUri === undefined
    ) {
      throw new WorkspaceValidationError("update command has no changes");
    }
    return command;
  }
  throw new WorkspaceValidationError(`unsupported workspace operation: ${value.type}`);
}

function assertManifest(manifest: ComponentManifest): void {
  if (!COMPONENT_ID_PATTERN.test(manifest.id)) {
    throw new WorkspaceValidationError(`invalid component id: ${manifest.id}`);
  }
  if (!manifest.title.trim() || !manifest.description.trim() || !manifest.version.trim()) {
    throw new WorkspaceValidationError(`component ${manifest.id} has incomplete metadata`);
  }
  if (manifest.supportedOperations.length === 0) {
    throw new WorkspaceValidationError(`component ${manifest.id} supports no operations`);
  }
  if (new Set(manifest.supportedOperations).size !== manifest.supportedOperations.length) {
    throw new WorkspaceValidationError(`component ${manifest.id} repeats an operation`);
  }
}

function validateVisualGraph(props: JsonObject): void {
  const rootId = props.root_id;
  const rawElements = props.elements;
  if (typeof rootId !== "string" || !Array.isArray(rawElements)) {
    throw new WorkspaceValidationError("visual composition requires a root and elements");
  }
  const byId = new Map<string, Record<string, unknown>>();
  for (const raw of rawElements) {
    if (!isRecord(raw) || typeof raw.id !== "string" || byId.has(raw.id)) {
      throw new WorkspaceValidationError("visual composition element IDs must be unique");
    }
    if (raw.type === "chart") {
      if (!Array.isArray(raw.labels) || !Array.isArray(raw.series)) {
        throw new WorkspaceValidationError("chart labels and series must be arrays");
      }
      for (const item of raw.series) {
        if (!isRecord(item) || !Array.isArray(item.values) || item.values.length !== raw.labels.length) {
          throw new WorkspaceValidationError("chart series values must match chart labels");
        }
        if (item.tones !== undefined && (!Array.isArray(item.tones) || item.tones.length !== raw.labels.length)) {
          throw new WorkspaceValidationError("chart point tones must match chart labels");
        }
      }
      if (
        typeof raw.y_min === "number" &&
        typeof raw.y_max === "number" &&
        raw.y_max <= raw.y_min
      ) {
        throw new WorkspaceValidationError("chart y_max must exceed y_min");
      }
    }
    byId.set(raw.id, raw);
  }
  if (!byId.has(rootId)) {
    throw new WorkspaceValidationError("visual composition root does not exist");
  }
  const parents = new Set<string>();
  for (const element of byId.values()) {
    if (element.type !== "group") continue;
    if (!Array.isArray(element.children)) {
      throw new WorkspaceValidationError("visual composition group children are invalid");
    }
    for (const childId of element.children) {
      if (typeof childId !== "string" || !byId.has(childId)) {
        throw new WorkspaceValidationError("visual composition references an unknown child");
      }
      if (parents.has(childId)) {
        throw new WorkspaceValidationError("visual elements may have only one parent");
      }
      parents.add(childId);
    }
  }
  if (parents.has(rootId)) {
    throw new WorkspaceValidationError("visual composition root may not have a parent");
  }
  const visited = new Set<string>();
  const active = new Set<string>();
  function visit(id: string): void {
    if (active.has(id)) {
      throw new WorkspaceValidationError("visual composition contains a cycle");
    }
    if (visited.has(id)) return;
    active.add(id);
    const element = byId.get(id);
    if (element?.type === "group" && Array.isArray(element.children)) {
      for (const childId of element.children) visit(String(childId));
    }
    active.delete(id);
    visited.add(id);
  }
  visit(rootId);
  if (visited.size !== byId.size) {
    throw new WorkspaceValidationError("visual composition contains unreachable elements");
  }
}

export class ComponentRegistry {
  readonly #manifests = new Map<string, ComponentManifest>();

  constructor(manifests: readonly ComponentManifest[]) {
    for (const manifest of manifests) {
      assertManifest(manifest);
      if (this.#manifests.has(manifest.id)) {
        throw new WorkspaceValidationError(`duplicate component id: ${manifest.id}`);
      }
      this.#manifests.set(manifest.id, manifest);
    }
  }

  list(): ComponentManifest[] {
    return [...this.#manifests.values()];
  }

  get(componentId: string): ComponentManifest | undefined {
    return this.#manifests.get(componentId);
  }

  validateProps(componentId: string, props: JsonObject): void {
    const manifest = this.#manifests.get(componentId);
    if (!manifest) {
      throw new WorkspaceValidationError(`unknown component: ${componentId}`);
    }
    const detail = schemaError(manifest.propsSchema, props);
    if (detail) {
      throw new WorkspaceValidationError(`invalid props for ${componentId}: ${detail}`);
    }
    if (componentId === "visual-composition") validateVisualGraph(props);
  }

  apply(state: WorkspaceState, commandValue: unknown): WorkspaceState {
    const command = parseWorkspaceCommand(commandValue);
    if (command.type === "open") {
      const manifest = this.#manifests.get(command.panel.componentId);
      if (!manifest) {
        throw new WorkspaceValidationError(`unknown component: ${command.panel.componentId}`);
      }
      this.#assertOperation(manifest, command.type);
      if (state.panels.some((panel) => panel.id === command.panel.id)) {
        throw new WorkspaceValidationError(`panel already exists: ${command.panel.id}`);
      }
      this.validateProps(command.panel.componentId, command.panel.props);
      return {
        panels: [command.panel],
        focusedPanelId: command.panel.id,
      };
    }

    const panelIndex = state.panels.findIndex((panel) => panel.id === command.panelId);
    if (panelIndex < 0) {
      throw new WorkspaceValidationError(`unknown panel: ${command.panelId}`);
    }
    const currentPanel = state.panels[panelIndex];
    if (!currentPanel) throw new WorkspaceValidationError("workspace panel is unavailable");
    const manifest = this.#manifests.get(currentPanel.componentId);
    if (!manifest) {
      throw new WorkspaceValidationError(`unknown component: ${currentPanel.componentId}`);
    }
    this.#assertOperation(manifest, command.type);

    if (command.type === "focus") {
      return { panels: [currentPanel], focusedPanelId: command.panelId };
    }
    if (command.type === "close") {
      const panels = state.panels.filter((panel) => panel.id !== command.panelId);
      const focusedPanelId =
        state.focusedPanelId === command.panelId
          ? panels.at(-1)?.id
          : state.focusedPanelId;
      return focusedPanelId === undefined ? { panels } : { panels, focusedPanelId };
    }

    const props = command.props ? { ...currentPanel.props, ...command.props } : currentPanel.props;
    this.validateProps(currentPanel.componentId, props);
    const panel: WorkspacePanel = {
      ...currentPanel,
      props,
      state: command.state ? { ...currentPanel.state, ...command.state } : currentPanel.state,
    };
    if (command.title === null) delete panel.title;
    else if (command.title !== undefined) panel.title = command.title;
    if (command.resourceUri === null) delete panel.resourceUri;
    else if (command.resourceUri !== undefined) panel.resourceUri = command.resourceUri;
    const panels = [...state.panels];
    panels[panelIndex] = panel;
    return { ...state, panels };
  }

  #assertOperation(manifest: ComponentManifest, operation: ComponentOperation): void {
    if (!manifest.supportedOperations.includes(operation)) {
      throw new WorkspaceValidationError(
        `component ${manifest.id} does not support ${operation}`,
      );
    }
  }
}

export const builtInComponentRegistry = new ComponentRegistry(
  BUILT_IN_COMPONENT_MANIFESTS,
);

export function emptyWorkspaceState(): WorkspaceState {
  return { panels: [] };
}

export function projectWorkspaceEvents(
  events: readonly WorkspaceEventLike[],
  registry: ComponentRegistry = builtInComponentRegistry,
): WorkspaceState {
  let state = emptyWorkspaceState();
  for (const event of events) {
    if (!WORKSPACE_EVENT_TYPES.has(event.type)) continue;
    state = registry.apply(state, event.payload.command);
  }
  return state;
}
