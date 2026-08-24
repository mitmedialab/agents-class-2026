/** TypeScript bindings for shared/schemas/v1/agent-core.schema.json. */

export const SCHEMA_VERSION = 1 as const;

export type Uuid = string;
export type DateTime = string;
export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export type Role = "public" | "student" | "ta" | "instructor" | "admin";
export type MemoryPrivacy = "personal" | "course_private";
export type CapabilityStatus = "available" | "obtainable" | "unavailable";
export type PermissionStatus = "requested" | "granted" | "denied" | "revoked";
export type NodeType =
  | "web"
  | "browser_extension"
  | "local_bridge"
  | "raspberry_pi"
  | "device";

export interface PrincipalContext {
  authenticated: boolean;
  user_id: Uuid | null;
  anonymous_session_id: Uuid | null;
  username: string | null;
  display_name: string | null;
  roles: Role[];
  session_id: Uuid;
}

export interface Event {
  id: Uuid;
  schema_version: typeof SCHEMA_VERSION;
  timestamp: DateTime;
  type: string;
  actor: string;
  principal_user_id: Uuid | null;
  anonymous_session_id: Uuid | null;
  conversation_id: Uuid | null;
  node_id: Uuid | null;
  payload: JsonObject;
  metadata: JsonObject;
}

export interface Conversation {
  id: Uuid;
  user_id: Uuid | null;
  anonymous_session_id: Uuid | null;
  created_at: DateTime;
  updated_at: DateTime;
  title: string | null;
  archived_at: DateTime | null;
}

export interface Memory {
  id: Uuid;
  user_id: Uuid;
  created_at: DateTime;
  updated_at: DateTime;
  kind: string;
  content: string;
  source_event_ids: Uuid[];
  privacy: MemoryPrivacy;
  metadata: JsonObject;
}

export interface CapabilityAcquisition {
  type: string;
  metadata: JsonObject;
}

export interface Capability {
  id: string;
  status: CapabilityStatus;
  acquisition: CapabilityAcquisition | null;
  node_id: Uuid | null;
  metadata: JsonObject;
}

export interface Permission {
  id: Uuid;
  capability: string;
  scope: JsonObject;
  status: PermissionStatus;
  principal_user_id: Uuid | null;
  anonymous_session_id: Uuid | null;
  node_id: Uuid | null;
  created_at: DateTime;
  updated_at: DateTime;
  metadata: JsonObject;
}

export interface Node {
  id: Uuid;
  user_id: Uuid | null;
  type: NodeType;
  name: string;
  capabilities: string[];
  online: boolean;
  last_seen_at: DateTime;
}

export interface AgentContext {
  principal: PrincipalContext;
  conversation_id: Uuid;
  recent_events: Event[];
  selected_memories: Memory[];
  capabilities: Capability[];
  permissions: Permission[];
  permitted_tool_ids: string[];
  permitted_resource_uris: string[];
  active_skill_ids: string[];
  metadata: JsonObject;
}

export interface AgentInput {
  id: Uuid;
  conversation_id: Uuid;
  text: string;
  metadata: JsonObject;
}

export interface AgentResult {
  id: Uuid;
  input_id: Uuid;
  conversation_id: Uuid;
  output_text: string;
  events: Event[];
  metadata: JsonObject;
}

export interface ContractMap {
  PrincipalContext: PrincipalContext;
  Event: Event;
  Conversation: Conversation;
  Memory: Memory;
  Capability: Capability;
  Permission: Permission;
  Node: Node;
  AgentContext: AgentContext;
  AgentInput: AgentInput;
  AgentResult: AgentResult;
}

export type ContractName = keyof ContractMap;
