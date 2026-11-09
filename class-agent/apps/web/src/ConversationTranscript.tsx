import type { Event } from "@class-agent/protocol";
import { useLayoutEffect, useRef } from "react";

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

const NEAR_BOTTOM_PX = 160;

interface ConversationChatProps {
  events: readonly Event[];
  /** The question of a run still in progress, which is not an event until the run finishes. */
  pendingMessage: string | null;
  /** The reply being written, or an error, when it is not yet the last saved message. */
  latestResponse: string;
}

/** A log opened from the drawer: the whole chat, in place, newest at the bottom. */
export function ConversationChat({ events, latestResponse, pendingMessage }: ConversationChatProps) {
  const chatRef = useRef<HTMLOListElement>(null);
  const messages = projectConversationTranscript(events);
  const newestFirst = [...messages].reverse();
  const lastStudent = newestFirst.find((message) => message.from === "student");
  const lastAgent = newestFirst.find((message) => message.from === "agent");
  const showPending = pendingMessage !== null && pendingMessage !== lastStudent?.text;
  // A saved reply with a platform note added below it should not repeat the reply.
  const latestAddition = lastAgent && latestResponse.startsWith(lastAgent.text)
    ? latestResponse.slice(lastAgent.text.length).trim()
    : latestResponse;
  const lengthRef = useRef(0);

  useLayoutEffect(() => {
    const stage = chatRef.current?.closest<HTMLElement>(".response-stage");
    if (!stage) return;
    const added = messages.length + (showPending ? 1 : 0) !== lengthRef.current;
    lengthRef.current = messages.length + (showPending ? 1 : 0);
    const nearBottom =
      stage.scrollHeight - stage.scrollTop - stage.clientHeight < NEAR_BOTTOM_PX;
    if (added || nearBottom) stage.scrollTop = stage.scrollHeight;
  });

  return (
    <ol aria-label="Chat history" className="conversation-chat" ref={chatRef}>
      {messages.map((message) => (
        <li data-from={message.from} key={message.id}>
          <p className="conversation-chat-meta">
            {message.from === "student" ? "You" : "Course Agent"}
            {" · "}
            <time dateTime={message.timestamp}>{formatConversationTime(message.timestamp)}</time>
          </p>
          {message.from === "student" ? (
            <p className="conversation-chat-student">{message.text}</p>
          ) : (
            <ResponseText text={message.text} />
          )}
        </li>
      ))}
      {showPending ? (
        <li data-from="student">
          <p className="conversation-chat-meta">You</p>
          <p className="conversation-chat-student">{pendingMessage}</p>
        </li>
      ) : null}
      {latestAddition ? (
        <li data-from="agent">
          <p className="conversation-chat-meta">Course Agent</p>
          <ResponseText text={latestAddition} />
        </li>
      ) : null}
    </ol>
  );
}
