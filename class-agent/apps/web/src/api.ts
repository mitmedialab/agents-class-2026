import type { Conversation, Event, PrincipalContext, Uuid } from "@class-agent/protocol";
import type { JsonValue } from "@class-agent/workspace";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined;
const API_BASE_URL = (configuredBaseUrl ?? "/api/v1").replace(/\/$/, "");
const UPLOAD_TIMEOUT_MS = 60_000;

export function courseResourceAssetUrl(resourceUri: string, assetId: string): string {
  const query = new URLSearchParams({ uri: resourceUri, asset_id: assetId }).toString();
  return `${API_BASE_URL}/course/resources/asset?${query}`;
}

export interface ConversationDetail {
  conversation: Conversation;
  events: Event[];
}

export interface TemporaryUpload {
  id: Uuid;
  filename: string;
  media_type: string;
  size_bytes: number;
  created_at: string;
  expires_at: string;
}

export interface CourseResourceContent {
  uri: string;
  mediaType: string;
  data: Uint8Array;
}

export type AgentActivityKind =
  | "status"
  | "run"
  | "tool"
  | "resource"
  | "output"
  | "complete"
  | "error";

export interface AgentActivity {
  id?: string;
  kind: AgentActivityKind;
  label: string;
  detail?: string;
}

export type AgentStreamEvent =
  | { kind: "text"; text: string }
  | { kind: "text_final"; text: string }
  | { kind: "progress"; text: string; replace: boolean }
  | { kind: "activity"; activity: AgentActivity }
  | { kind: "workspace"; command: unknown }
  | { kind: "application_submitted" }
  | { kind: "done" }
  | { kind: "error" };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (isRecord(body) && typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // A transport error without JSON still receives a stable client message.
  }
  return "request failed";
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }

  return (await response.json()) as T;
}

export function getPrincipal(): Promise<PrincipalContext> {
  return requestJson<PrincipalContext>("/auth/me");
}

export function login(username: string, accessCode: string): Promise<PrincipalContext> {
  return requestJson<PrincipalContext>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, access_code: accessCode }),
  });
}

export async function logout(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
}

export function listConversations(): Promise<Conversation[]> {
  return requestJson<Conversation[]>("/conversations");
}

export function createConversation(title: string): Promise<Conversation> {
  return requestJson<Conversation>("/conversations", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export function getConversation(conversationId: Uuid): Promise<ConversationDetail> {
  return requestJson<ConversationDetail>(`/conversations/${conversationId}`);
}

export async function getCourseResourceContent(
  resourceUri: string,
): Promise<CourseResourceContent> {
  const uploadId = resourceUri.startsWith("upload://")
    ? resourceUri.slice("upload://".length)
    : null;
  const path = uploadId
    ? `/uploads/${encodeURIComponent(uploadId)}/content`
    : `/course/resources/content?${new URLSearchParams({ uri: resourceUri }).toString()}`;
  const response = await fetch(`${API_BASE_URL}${path}`, { credentials: "include" });
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  const mediaType = response.headers.get("content-type")?.split(";", 1)[0] ?? "text/plain";
  return {
    uri: resourceUri,
    mediaType,
    data: new Uint8Array(await response.arrayBuffer()),
  };
}

export function applyWorkspacePanelAction(
  conversationId: Uuid,
  action: "focus" | "close",
  panelId: Uuid,
): Promise<Event> {
  return requestJson<Event>(`/conversations/${conversationId}/workspace/actions`, {
    method: "POST",
    body: JSON.stringify({ action, panel_id: panelId }),
  });
}

export function ensureApplicationDraft(conversationId: Uuid): Promise<Event> {
  return requestJson<Event>(`/conversations/${conversationId}/application-draft`, {
    method: "POST",
  });
}

export function recordWorkspaceInteraction(
  conversationId: Uuid,
  panelId: Uuid,
  action:
    | "calendar.select_event"
    | "calendar.change_view"
    | "document.change_page"
    | "document.find_text"
    | "page_cards.select"
    | "visual.change"
    | "draft.change",
  value: JsonValue,
): Promise<Event> {
  return requestJson<Event>(`/conversations/${conversationId}/workspace/interactions`, {
    method: "POST",
    body: JSON.stringify({ panel_id: panelId, action, value }),
  });
}

export function browserSnapshotUrl(
  conversationId: Uuid,
  sessionId: Uuid,
  revision: number,
): string {
  return (
    `${API_BASE_URL}/conversations/${conversationId}/browser/${sessionId}/snapshot` +
    `?revision=${revision}`
  );
}

export function browserPreviewSnapshotUrl(
  conversationId: Uuid,
  previewId: Uuid,
  revision: number,
): string {
  return (
    `${API_BASE_URL}/conversations/${conversationId}/browser/previews/${previewId}/snapshot` +
    `?revision=${revision}`
  );
}

export function scrollBrowserSession(
  conversationId: Uuid,
  panelId: Uuid,
  sessionId: Uuid,
  deltaY: number,
): Promise<Event> {
  return requestJson<Event>(
    `/conversations/${conversationId}/browser/${sessionId}/scroll`,
    {
      method: "POST",
      body: JSON.stringify({ panel_id: panelId, delta_y: deltaY }),
    },
  );
}

export function clickBrowserSession(
  conversationId: Uuid,
  panelId: Uuid,
  sessionId: Uuid,
  x: number,
  y: number,
): Promise<Event> {
  return requestJson<Event>(
    `/conversations/${conversationId}/browser/${sessionId}/click`,
    {
      method: "POST",
      body: JSON.stringify({ panel_id: panelId, x, y }),
    },
  );
}

export function resizeBrowserSession(
  conversationId: Uuid,
  panelId: Uuid,
  sessionId: Uuid,
  width: number,
  height: number,
): Promise<Event> {
  return requestJson<Event>(
    `/conversations/${conversationId}/browser/${sessionId}/resize`,
    {
      method: "POST",
      body: JSON.stringify({ panel_id: panelId, width, height }),
    },
  );
}

function uploadMediaType(file: File): string {
  if (file.type) return file.type;
  const extension = file.name.split(".").at(-1)?.toLowerCase();
  return (
    {
      csv: "text/csv",
      json: "application/json",
      md: "text/markdown",
      pdf: "application/pdf",
      txt: "text/plain",
    }[extension ?? ""] ?? "application/octet-stream"
  );
}

export async function uploadFile(file: File): Promise<TemporaryUpload> {
  const query = new URLSearchParams({ filename: file.name });
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE_URL}/uploads?${query.toString()}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": uploadMediaType(file) },
      body: file,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new ApiError(await errorMessage(response), response.status);
    }
    return (await response.json()) as TemporaryUpload;
  } catch (error) {
    if (controller.signal.aborted) {
      throw new ApiError("Upload timed out. Please try again.", 408);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function jsonDetail(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function activity(
  kind: AgentActivityKind,
  label: string,
  detail?: string,
): AgentActivity {
  return detail ? { kind, label, detail } : { kind, label };
}

const RESOURCE_ACTIVITY_LABELS: Record<string, string> = {
  "course://application": "application information",
  "course://faq": "course information index",
  "course://instructors": "course staff",
  "course://repositories": "student repositories",
  "course://schedule": "course schedule",
  "course://syllabus": "course syllabus",
};

const TOOL_ACTIVITY_LABELS: Record<string, string> = {
  "course.get_application": "Reading application information",
  "course.get_schedule": "Reading course schedule",
  "course.read_public_file": "Reading course information",
  "course.read_syllabus": "Reading course syllabus",
  "course.search": "Searching course information",
  "course.search_faq": "Searching course information",
  "course.show_public_files": "Checking available course information",
  "course.submit_application": "Submitting application",
  "web.search": "Searching the public web",
  "web.search_images": "Searching public images",
  "web.visit": "Reading a public webpage",
  "browser.open": "Opening remote browser",
  "browser.navigate": "Navigating remote browser",
  "browser.scroll": "Scrolling remote browser",
  "browser.highlight_text": "Highlighting page content",
  "workspace.close_component": "Closing workspace panel",
  "workspace.focus_component": "Focusing workspace panel",
  "workspace.list_components": "Checking workspace components",
  "workspace.open_component": "Opening workspace panel",
  "workspace.update_component": "Updating workspace panel",
};

function toolActivityLabel(toolId: string | null): string {
  return toolId
    ? (TOOL_ACTIVITY_LABELS[toolId] ?? "Using course information")
    : "Using course information";
}

function platformActivity(data: Record<string, unknown>): AgentActivity | null {
  const type = typeof data.type === "string" ? data.type : "";
  const event = isRecord(data.event) ? data.event : null;
  const payload = event && isRecord(event.payload) ? event.payload : null;
  const metadata = event && isRecord(event.metadata) ? event.metadata : null;
  const toolId = payload && typeof payload.tool_id === "string" ? payload.tool_id : null;
  if (type === "agent.run.started") {
    const runtime = metadata && typeof metadata.runtime === "string" ? metadata.runtime : null;
    const model = metadata && typeof metadata.model === "string" ? metadata.model : null;
    return activity(
      "run",
      "Planning response",
      [runtime, model].filter(Boolean).join(" · ") || undefined,
    );
  }
  if (type === "resource.read") {
    const uri = payload && typeof payload.uri === "string" ? payload.uri : null;
    const resourceLabel = uri ? RESOURCE_ACTIVITY_LABELS[uri] : null;
    return activity(
      "resource",
      resourceLabel ? `Reading ${resourceLabel}` : "Reading course information",
    );
  }
  if (type === "agent.tool.requested" || type === "tool.started") {
    const label = toolActivityLabel(toolId);
    const rawArguments = payload?.arguments;
    const argumentDetail =
      isRecord(rawArguments) && Object.keys(rawArguments).length === 0
        ? undefined
        : jsonDetail(rawArguments);
    return activity(
      "tool",
      label,
      toolId === "course.submit_application" ? undefined : argumentDetail,
    );
  }
  if (type === "agent.tool.completed") {
    return activity("complete", `${toolActivityLabel(toolId)} complete`);
  }
  if (type === "agent.tool.failed") {
    return activity(
      "error",
      `${toolActivityLabel(toolId)} failed`,
      jsonDetail(payload?.error),
    );
  }
  return null;
}

function parseSseBlock(block: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  try {
    return { event, data: JSON.parse(dataLines.join("\n")) as unknown };
  } catch {
    return null;
  }
}

function emitSseEvent(
  parsed: { event: string; data: unknown },
  onEvent: (event: AgentStreamEvent) => void,
): void {
  if (!isRecord(parsed.data)) {
    return;
  }
  if (parsed.event === "message" && typeof parsed.data.text === "string") {
    onEvent({
      kind: parsed.data.type === "agent.text.done" ? "text_final" : "text",
      text: parsed.data.text,
    });
    return;
  }
  if (parsed.event === "progress" && typeof parsed.data.text === "string") {
    onEvent({
      kind: "progress",
      text: parsed.data.text,
      replace: parsed.data.replace === true,
    });
    return;
  }
  if (parsed.event === "status" && typeof parsed.data.label === "string") {
    onEvent({
      kind: "activity",
      activity: activity(
        "status",
        parsed.data.label,
        typeof parsed.data.stage === "string" ? parsed.data.stage : undefined,
      ),
    });
    return;
  }
  if (parsed.event === "platform") {
    const type = typeof parsed.data.type === "string" ? parsed.data.type : "";
    const platformEvent = isRecord(parsed.data.event) ? parsed.data.event : null;
    const payload = platformEvent && isRecord(platformEvent.payload) ? platformEvent.payload : null;
    if (type.startsWith("workspace.panel.") && payload?.command !== undefined) {
      onEvent({ kind: "workspace", command: payload.command });
      return;
    }
    if (
      type === "agent.tool.completed" &&
      payload?.tool_id === "course.submit_application"
    ) {
      onEvent({ kind: "application_submitted" });
    }
    const activity = platformActivity(parsed.data);
    if (activity) {
      onEvent({ kind: "activity", activity });
    }
    return;
  }
  if (parsed.event === "done") {
    onEvent({ kind: "done" });
    return;
  }
  if (parsed.event === "error") {
    onEvent({ kind: "error" });
  }
}

export async function streamAgentRun(
  conversationId: Uuid,
  text: string,
  onEvent: (event: AgentStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const request: RequestInit = {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ text }),
  };
  if (signal) {
    request.signal = signal;
  }
  const response = await fetch(
    `${API_BASE_URL}/conversations/${conversationId}/run/stream`,
    request,
  );

  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  if (!response.body) {
    throw new ApiError("streaming is unavailable", response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const result = await reader.read();
    buffer += decoder.decode(result.value, { stream: !result.done });
    buffer = buffer.replaceAll("\r\n", "\n");

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseBlock(block);
      if (parsed) {
        emitSseEvent(parsed, onEvent);
      }
      boundary = buffer.indexOf("\n\n");
    }

    if (result.done) {
      const parsed = parseSseBlock(buffer);
      if (parsed) {
        emitSseEvent(parsed, onEvent);
      }
      return;
    }
  }
}
