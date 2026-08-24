import { describe, expect, it, vi } from "vitest";
import { streamAgentRun, type AgentStreamEvent } from "./api.js";

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
            '\nevent: progress\ndata: {"type":"agent.progress.delta","text":"I’ll read the syllabus."}\n\n',
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
          label: "Reading course://syllabus",
          detail: "course://syllabus",
        },
      },
      { kind: "progress", text: "I’ll read the syllabus." },
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
