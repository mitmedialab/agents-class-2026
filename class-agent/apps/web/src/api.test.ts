import { describe, expect, it, vi } from "vitest";
import {
  getCourseResourceContent,
  streamAgentRun,
  uploadFile,
  type AgentStreamEvent,
} from "./api.js";

describe("agent event stream", () => {
  it("parses split CRLF events into process and text updates", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'event: status\r\ndata: {"type":"agent.status","label":"Preparing conversation context"}\r\n\r',
          ),
        );
        controller.enqueue(encoder.encode("\nevent: platform\r"));
        controller.enqueue(
          encoder.encode(
            '\ndata: {"type":"resource.read","event":{"payload":{"uri":"course://syllabus"}}}\r\n\r',
          ),
        );
        controller.enqueue(
          encoder.encode(
            '\nevent: platform\ndata: {"type":"agent.tool.requested","event":{"payload":{"tool_id":"course.get_application","arguments":{}}}}\n\n',
          ),
        );
        controller.enqueue(
          encoder.encode(
            '\nevent: platform\ndata: {"type":"workspace.panel.opened","event":{"payload":{"command":{"type":"open","panel":{"id":"40000000-0000-4000-8000-000000000001","component_id":"calendar","resource_uri":"course://schedule","props":{"view":"agenda"},"state":{}}}}}}\n\n',
          ),
        );
        controller.enqueue(
          encoder.encode(
            '\nevent: progress\ndata: {"type":"agent.progress.delta","text":"I’ll read the syllabus.","replace":true}\n\n',
          ),
        );
        controller.enqueue(
          encoder.encode(
            '\nevent: message\ndata: {"type":"agent.text.delta","text":"Hello"}\n\n',
          ),
        );
        controller.enqueue(
          encoder.encode(
            'event: message\ndata: {"type":"agent.text.done","text":"Hello world"}\n\n',
          ),
        );
        controller.enqueue(
          encoder.encode('event: done\ndata: {"type":"agent.run.completed"}\n\n'),
        );
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue({
      body: stream,
      ok: true,
      status: 200,
    });
    vi.stubGlobal("fetch", fetchMock);
    const events: AgentStreamEvent[] = [];

    await streamAgentRun(
      "20000000-0000-4000-8000-000000000001",
      "hello",
      (event) => events.push(event),
    );

    expect(events).toEqual([
      {
        kind: "activity",
        activity: {
          kind: "status",
          label: "Preparing conversation context",
        },
      },
      {
        kind: "activity",
        activity: {
          kind: "resource",
          label: "Reading course syllabus",
        },
      },
      {
        kind: "activity",
        activity: {
          kind: "tool",
          label: "Reading application information",
        },
      },
      {
        kind: "workspace",
        command: {
          type: "open",
          panel: {
            id: "40000000-0000-4000-8000-000000000001",
            component_id: "calendar",
            resource_uri: "course://schedule",
            props: { view: "agenda" },
            state: {},
          },
        },
      },
      { kind: "progress", text: "I’ll read the syllabus.", replace: true },
      { kind: "text", text: "Hello" },
      { kind: "text_final", text: "Hello world" },
      { kind: "done" },
    ]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/conversations/20000000-0000-4000-8000-000000000001/run/stream",
      expect.objectContaining({ credentials: "include", method: "POST" }),
    );
    vi.unstubAllGlobals();
  });
});

describe("temporary uploads", () => {
  it("sends raw file bytes with a filename query and content type", async () => {
    const upload = {
      id: "40000000-0000-4000-8000-000000000001",
      filename: "face photo.png",
      media_type: "image/png",
      size_bytes: 8,
      created_at: "2026-08-23T10:00:00Z",
      expires_at: "2026-08-24T10:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: vi.fn().mockResolvedValue(upload),
    });
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["contents"], "face photo.png", { type: "image/png" });

    await expect(uploadFile(file)).resolves.toEqual(upload);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/uploads?filename=face+photo.png",
      expect.objectContaining({
        body: file,
        credentials: "include",
        headers: { "Content-Type": "image/png" },
        method: "POST",
      }),
    );
    vi.unstubAllGlobals();
  });

  it("reads an upload resource from its principal-scoped content route", async () => {
    const bytes = new Uint8Array([37, 80, 68, 70]);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/pdf" }),
      arrayBuffer: vi.fn().mockResolvedValue(bytes.buffer),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      getCourseResourceContent("upload://40000000-0000-4000-8000-000000000001"),
    ).resolves.toEqual({
      uri: "upload://40000000-0000-4000-8000-000000000001",
      mediaType: "application/pdf",
      data: bytes,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/uploads/40000000-0000-4000-8000-000000000001/content",
      { credentials: "include" },
    );
    vi.unstubAllGlobals();
  });
});
