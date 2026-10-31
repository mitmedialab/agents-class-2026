import type { Event } from "@class-agent/protocol";
import {
  emptyWorkspaceState,
  projectWorkspaceEvents,
  type WorkspaceState,
} from "@class-agent/workspace";

export interface ConversationMoment {
  id: string;
  response: string;
  timestamp: string;
  userMessage?: string;
  workspace: WorkspaceState;
}

const USER_REQUEST_PATTERN = /<user_request>\s*([\s\S]*?)\s*<\/user_request>/i;
const TEMPORARY_UPLOAD_PATTERN = /\n*\[Temporary upload:[^\]]+]/g;

export function visibleUserMessage(value: string): string {
  const explicitRequest = USER_REQUEST_PATTERN.exec(value)?.[1];
  const visible = (explicitRequest ?? value).replaceAll(TEMPORARY_UPLOAD_PATTERN, "");
  return visible.trim();
}

function responseFromEvent(event: Event): string | null {
  if (
    event.type === "email.ta_answer.received" &&
    typeof event.payload.answer === "string"
  ) {
    return `Course staff replied:\n\n${event.payload.answer}`;
  }
  if (event.type === "agent.message" && typeof event.payload.text === "string") {
    return event.payload.text;
  }
  return null;
}

function workspaceAt(events: readonly Event[], index: number): WorkspaceState {
  try {
    return projectWorkspaceEvents(events.slice(0, index + 1));
  } catch {
    return emptyWorkspaceState();
  }
}

export function projectConversationTimeline(
  events: readonly Event[],
): ConversationMoment[] {
  const moments: ConversationMoment[] = [];
  let pendingUserMessage: string | undefined;
  events.forEach((event, index) => {
    if (event.type === "user.message" && typeof event.payload.text === "string") {
      pendingUserMessage = visibleUserMessage(event.payload.text) || undefined;
      return;
    }
    const response = responseFromEvent(event);
    if (!response) return;
    moments.push({
      id: event.id,
      response,
      timestamp: event.timestamp,
      ...(pendingUserMessage ? { userMessage: pendingUserMessage } : {}),
      workspace: workspaceAt(events, index),
    });
    pendingUserMessage = undefined;
  });
  return moments;
}

export function latestConversationResponse(events: readonly Event[]): string {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (!event) continue;
    const response = responseFromEvent(event);
    if (response) return response;
  }
  return "";
}

export function momentAtOffset(
  moments: readonly ConversationMoment[],
  offset: number,
): ConversationMoment | null {
  return moments.at(-(Math.max(0, offset) + 1)) ?? null;
}

// The layout changes only while both moments are black, so text never refits on screen.
export function timelineFade(progress: number) {
  const bounded = Math.min(1, Math.max(0, progress));
  const outgoing = Math.max(0, 1 - bounded / 0.44);
  const incoming = Math.max(0, Math.min(1, (bounded - 0.56) / 0.44));
  const layout = Math.max(0, Math.min(1, (bounded - 0.44) / 0.12));
  return { outgoing, incoming, layout };
}

interface ConversationTimelineProps {
  disabled?: boolean;
  moments: readonly ConversationMoment[];
  offset: number;
  previewOffset?: number | null;
  progress?: number;
  onOffsetChange: (offset: number) => void;
}

export function ConversationTimeline({
  disabled = false,
  moments,
  offset,
  previewOffset = null,
  progress = 0,
  onOffsetChange,
}: ConversationTimelineProps) {
  if (moments.length < 2) return null;
  const shownOffset = previewOffset !== null && progress >= 0.5 ? previewOffset : offset;
  const shownTurn = moments.length - shownOffset;
  const pulling = previewOffset !== null;
  const markerCount = Math.min(moments.length, 11);
  const scrubbedOffset = offset + (
    pulling ? (previewOffset - offset) * Math.min(1, Math.max(0, progress)) : 0
  );
  const markerPosition = (
    ((moments.length - 1 - scrubbedOffset) / (moments.length - 1)) * (markerCount - 1)
  );

  return (
    <nav
      aria-label="Conversation timeline"
      className="conversation-timeline"
      data-active={pulling || offset > 0 ? "true" : "false"}
      data-scrubbing={pulling ? "true" : "false"}
    >
      <button
        aria-label={offset > 0 ? "Return to current response" : "Go to an older assistant response"}
        aria-description={`Moment ${shownTurn} of ${moments.length}`}
        className="timeline-pager"
        disabled={disabled}
        onClick={() => onOffsetChange(offset > 0 ? 0 : 1)}
        type="button"
      >
        <span aria-hidden="true" className="timeline-pager-markers">
          {Array.from({ length: markerCount }, (_, index) => (
            <span className="timeline-pager-marker" key={index} />
          ))}
          <span
            className="timeline-pager-position"
            style={{ transform: `translate3d(${markerPosition * 15}px, -50%, 0)` }}
          />
        </span>
      </button>
      <button
        aria-label="Go to a newer assistant response"
        className="visually-hidden timeline-keyboard-next"
        disabled={disabled || offset === 0}
        onClick={() => onOffsetChange(offset - 1)}
        type="button"
      >
        Newer response
      </button>
      {offset > 0 ? (
        <button
          aria-label="Go to an older assistant response"
          className="visually-hidden timeline-keyboard-older"
          disabled={disabled || offset >= moments.length - 1}
          onClick={() => onOffsetChange(offset + 1)}
          type="button"
        >
          Older response
        </button>
      ) : null}
    </nav>
  );
}
