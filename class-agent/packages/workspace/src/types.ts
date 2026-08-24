export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonObject = { [key: string]: JsonValue };

export type ComponentOperation = "open" | "update" | "focus" | "close";

export interface ComponentManifest {
  id: string;
  version: string;
  title: string;
  description: string;
  propsSchema: JsonObject;
  supportedOperations: ComponentOperation[];
  defaultSize?: {
    width: number;
    height: number;
  };
}

export interface WorkspacePanel {
  id: string;
  componentId: string;
  title?: string;
  resourceUri?: string;
  props: JsonObject;
  state: JsonObject;
  layout?: {
    width?: number;
    height?: number;
  };
}

export interface WorkspaceState {
  panels: WorkspacePanel[];
  focusedPanelId?: string;
}

export interface DocumentHighlightAnchor {
  resourceUri: string;
  page: number;
  quote: string;
  prefix?: string;
  suffix?: string;
}

export interface OpenWorkspaceCommand {
  type: "open";
  panel: WorkspacePanel;
}

export interface UpdateWorkspaceCommand {
  type: "update";
  panelId: string;
  props?: JsonObject;
  state?: JsonObject;
  title?: string | null;
  resourceUri?: string | null;
}

export interface FocusWorkspaceCommand {
  type: "focus";
  panelId: string;
}

export interface CloseWorkspaceCommand {
  type: "close";
  panelId: string;
}

export type WorkspaceCommand =
  | OpenWorkspaceCommand
  | UpdateWorkspaceCommand
  | FocusWorkspaceCommand
  | CloseWorkspaceCommand;

export interface WorkspaceEventLike {
  type: string;
  payload: { [key: string]: unknown };
}
