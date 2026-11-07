import type { Event } from "@class-agent/protocol";
import { Button } from "@class-agent/ui";
import { useEffect, useRef } from "react";

import { ResponseText } from "./AgentResponse.js";
import { responseFromEvent, visibleUserMessage } from "./ConversationTimeline.js";

export interface TranscriptMessage {
  id: string;
  from: "student" | "agent";
  text: string;
  timestamp: string;
}

/** A browser projection of canonical events. Tool activity is left out on purpose. */
export function projectConversationTranscript(events: readonly Event[]): TranscriptMessage[] {
  const messages: TranscriptMessage[] = [];
  for (const event of events) {
    if (event.type === "user.message" && typeof event.payload.text === "string") {
      const text = visibleUserMessage(event.payload.text);
      if (text) messages.push({ id: event.id, from: "student", text, timestamp: event.timestamp });
      continue;
    }
    const response = responseFromEvent(event);
    if (response) {
      messages.push({ id: event.id, from: "agent", text: response, timestamp: event.timestamp });
    }
  }
  return messages;
}

export function formatConversationTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

interface ConversationTranscriptProps {
  events: readonly Event[];
  title: string;
  onClose: () => void;
}

export function ConversationTranscript({ events, title, onClose }: ConversationTranscriptProps) {
  const dialogRef = useRef<HTMLElement>(null);
  const messages = projectConversationTranscript(events);

  useEffect(() => {
    dialogRef.current?.querySelector("button")?.focus();
    function closeOnEscape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div className="drawer-backdrop" onClick={onClose} role="presentation">
      <section
        aria-label="Full conversation"
        aria-modal="true"
        className="conversation-transcript"
        onClick={(event) => event.stopPropagation()}
        ref={dialogRef}
        role="dialog"
      >
        <header className="conversation-transcript-heading">
          <div>
            <h2>{title}</h2>
            {messages[0] ? (
              <time dateTime={messages[0].timestamp}>
                {formatConversationTime(messages[0].timestamp)}
              </time>
            ) : null}
          </div>
          <Button onClick={onClose} variant="outline">
            Continue this conversation
          </Button>
        </header>
        {messages.length === 0 ? (
          <p className="empty-list">No messages in this conversation yet.</p>
        ) : (
          <ol className="conversation-transcript-messages">
            {messages.map((message) => (
              <li data-from={message.from} key={message.id}>
                <p className="conversation-transcript-meta">
                  {message.from === "student" ? "You" : "Course Agent"}
                  {" · "}
                  <time dateTime={message.timestamp}>
                    {formatConversationTime(message.timestamp)}
                  </time>
                </p>
                {message.from === "student" ? (
                  <p className="conversation-transcript-student">{message.text}</p>
                ) : (
                  <ResponseText text={message.text} />
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
