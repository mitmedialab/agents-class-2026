import type { Conversation, Event, PrincipalContext, Uuid } from "@class-agent/protocol";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined;
const API_BASE_URL = (configuredBaseUrl ?? "/api/v1").replace(/\/$/, "");

export interface ConversationDetail {
  conversation: Conversation;
  events: Event[];
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
  | { kind: "progress"; text: string }
  | { kind: "activity"; activity: AgentActivity }
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
    return activity(
      "resource",
      uri ? `Reading ${uri}` : "Reading course material",
      uri ?? undefined,
    );
  }
  if (type === "agent.tool.requested" || type === "tool.started") {
    return activity(
      "tool",
      toolId ? `Running ${toolId}` : "Running course tool",
      jsonDetail(payload?.arguments),
    );
  }
  if (type === "agent.tool.completed") {
    return activity(
      "complete",
      toolId ? `Completed ${toolId}` : "Tool complete",
      jsonDetail(payload?.result ?? payload?.resource_uris),
    );
  }
  if (type === "agent.tool.failed") {
    return activity(
      "error",
      toolId ? `${toolId} failed` : "Tool failed",
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
    onEvent({ kind: "progress", text: parsed.data.text });
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
