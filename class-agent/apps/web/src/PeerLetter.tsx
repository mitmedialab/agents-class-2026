import { useEffect, useRef } from "react";

import { Button } from "@class-agent/ui";

import type { NotificationCenterItem } from "./api.js";

// Which letters this browser has already played. A per-viewer presentation convenience,
// not canonical state: losing it only means a letter plays once more.
const SEEN_KEY = "class-agent.peer-letters-seen";
const SEEN_LIMIT = 50;

export function readSeenPeerLetters(): string[] {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(SEEN_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

export function markPeerLetterSeen(id: string): string[] {
  const seen = [...readSeenPeerLetters().filter((item) => item !== id), id].slice(-SEEN_LIMIT);
  try {
    window.localStorage.setItem(SEEN_KEY, JSON.stringify(seen));
  } catch {
    // Storage can be unavailable (private mode); the letter simply may replay.
  }
  return seen;
}

/** The newest classmate request or acceptance this browser has not yet presented. */
export function nextPeerLetter(
  items: readonly NotificationCenterItem[],
  seen: readonly string[],
): NotificationCenterItem | null {
  return (
    items.find(
      (item) =>
        !seen.includes(item.id) &&
        ((item.kind === "peer_request" && item.state === "pending") ||
          (item.kind === "peer_reply" && item.unread)),
    ) ?? null
  );
}

function senderLabel(item: NotificationCenterItem): string {
  return item.sender?.display_name ?? item.sender?.first_name ?? "A classmate";
}

export function PeerLetter({
  item,
  onOpen,
  onClose,
}: {
  item: NotificationCenterItem;
  onOpen: () => void;
  onClose: () => void;
}) {
  const paper = useRef<HTMLElement>(null);
  const request = item.kind === "peer_request";
  const name = senderLabel(item);
  const headingId = `peer-letter-${item.id}`;

  // Focus the primary action once, when the letter opens.
  useEffect(() => {
    paper.current?.querySelector("button")?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="peer-letter-backdrop" onClick={onClose} role="presentation">
      <div
        aria-labelledby={headingId}
        aria-modal="true"
        className="peer-letter-stage"
        data-kind={item.kind}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <div aria-hidden="true" className="peer-letter-envelope">
          <svg className="peer-letter-envelope-body" viewBox="0 0 160 104">
            <rect height="102" width="158" x="1" y="1" />
            <path d="M1 103 62 52M159 103 98 52" />
          </svg>
          <svg className="peer-letter-envelope-flap" viewBox="0 0 160 62">
            <path d="M1 1h158L80 61z" />
          </svg>
        </div>
        <article className="peer-letter-paper" ref={paper}>
          <p className="peer-letter-from">
            {request ? `A letter from ${name}` : `${name} wrote back`}
          </p>
          <h2 id={headingId}>{item.title}</h2>
          {request ? <p className="peer-letter-message">{item.detail}</p> : null}
          <p className="peer-letter-note">
            {request
              ? "Explaining something is one of the best ways to understand it yourself."
              : item.detail}
          </p>
          <div className="peer-letter-actions">
            <Button onClick={onOpen} variant="outline">
              {request ? "Answer in People" : "Open in People"}
            </Button>
            <Button onClick={onClose}>Later</Button>
          </div>
        </article>
      </div>
    </div>
  );
}
