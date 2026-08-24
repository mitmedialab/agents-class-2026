export {
  BUILT_IN_COMPONENT_MANIFESTS,
  CALENDAR_MANIFEST,
  DOCUMENT_VIEWER_MANIFEST,
  VISUAL_COMPOSITION_MANIFEST,
} from "./manifests.js";
export {
  ComponentRegistry,
  WorkspaceValidationError,
  builtInComponentRegistry,
  emptyWorkspaceState,
  parseWorkspaceCommand,
  projectWorkspaceEvents,
} from "./registry.js";
export type {
  CloseWorkspaceCommand,
  ComponentManifest,
  ComponentOperation,
  DocumentHighlightAnchor,
  FocusWorkspaceCommand,
  JsonObject,
  JsonValue,
  OpenWorkspaceCommand,
  UpdateWorkspaceCommand,
  WorkspaceCommand,
  WorkspaceEventLike,
  WorkspacePanel,
  WorkspaceState,
} from "./types.js";
