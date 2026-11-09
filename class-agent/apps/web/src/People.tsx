import { useEffect, useState } from "react";

import {
  actOnIntroduction,
  deleteMyMemory,
  getMyPeople,
  updateMyMemory,
  type MemoryKind,
  type MemoryPrivacy,
  type PeerIntroduction,
  type PeopleOverview,
  type StudentMemory,
} from "./api.js";

const KIND_LABELS: Record<MemoryKind, string> = {
  background: "Background",
  goal: "Goal",
  preference: "Preference",
  project: "Project",
  can_help: "Can help with",
  needs_help: "Needs help with",
};

const PRIVACY_LABELS: Record<MemoryPrivacy, string> = {
  personal: "Only me",
  course_private: "Classmates looking for help",
};

const STATUS_LABELS: Record<PeerIntroduction["status"], string> = {
  draft: "Draft, not sent",
  sent: "Waiting for a reply",
  accepted: "Accepted",
  declined: "You declined",
  unavailable: "Not available this time",
  cancelled: "Cancelled",
};

function shortDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function MemoryCard({
  memory,
  onChanged,
  onDeleted,
}: {
  memory: StudentMemory;
  onChanged: (memory: StudentMemory) => void;
  onDeleted: (memoryId: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(memory.content);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(update: { content?: string; privacy?: MemoryPrivacy }) {
    setBusy(true);
    setError(null);
    try {
      const { memory: updated } = await updateMyMemory(memory.id, update);
      onChanged(updated);
      setEditing(false);
    } catch {
      setError("Could not save this change.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteMyMemory(memory.id);
      onDeleted(memory.id);
    } catch {
      setError("Could not delete this memory.");
      setBusy(false);
    }
  }

  return (
    <li className="people-memory" data-kind={memory.kind}>
      <header>
        <span className="people-memory-kind">{KIND_LABELS[memory.kind]}</span>
        <span className="people-memory-date">
          {memory.edited_by_student ? "Edited by you" : "Saved by the agent"} ·{" "}
          {shortDate(memory.updated_at)}
        </span>
      </header>
      {editing ? (
        <textarea
          aria-label={`Edit ${KIND_LABELS[memory.kind].toLowerCase()} memory`}
          maxLength={500}
          onChange={(event) => setDraft(event.target.value)}
          rows={2}
          value={draft}
        />
      ) : (
        <p>{memory.content}</p>
      )}
      {memory.source_excerpt ? (
        <blockquote title="The message this memory came from">
          From your message: “{memory.source_excerpt}”
        </blockquote>
      ) : null}
      <footer>
        <label>
          Visible to
          <select
            disabled={busy}
            onChange={(event) => void save({ privacy: event.target.value as MemoryPrivacy })}
            value={memory.privacy}
          >
            <option value="personal">{PRIVACY_LABELS.personal}</option>
            <option value="course_private">{PRIVACY_LABELS.course_private}</option>
          </select>
        </label>
        <span className="people-actions">
          {editing ? (
            <>
              <button
                disabled={busy || draft.trim() === ""}
                onClick={() => void save({ content: draft })}
                type="button"
              >
                Save
              </button>
              <button
                disabled={busy}
                onClick={() => {
                  setDraft(memory.content);
                  setEditing(false);
                }}
                type="button"
              >
                Cancel
              </button>
            </>
          ) : (
            <button disabled={busy} onClick={() => setEditing(true)} type="button">
              Correct
            </button>
          )}
          <button disabled={busy} onClick={() => void remove()} type="button">
            Forget
          </button>
        </span>
      </footer>
      {error ? <p role="alert">{error}</p> : null}
    </li>
  );
}

function IntroductionCard({
  introduction,
  onUpdated,
}: {
  introduction: PeerIntroduction;
  onUpdated: (introductions: PeerIntroduction[]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const outgoing = introduction.direction === "outgoing";

  async function act(action: "send" | "cancel" | "accept" | "decline") {
    setBusy(true);
    setError(null);
    try {
      onUpdated((await actOnIntroduction(introduction.id, action)).introductions);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update this introduction.");
    } finally {
      setBusy(false);
    }
  }

  const actions: Array<["send" | "cancel" | "accept" | "decline", string]> = outgoing
    ? introduction.status === "draft"
      ? [["send", "Send"], ["cancel", "Discard"]]
      : introduction.status === "sent"
        ? [["cancel", "Withdraw"]]
        : []
    : introduction.status === "sent"
      ? [["accept", "Accept"], ["decline", "Decline"]]
      : [];

  return (
    <li className="people-introduction" data-status={introduction.status}>
      <header>
        <strong>
          {outgoing ? "To " : "From "}
          {introduction.other.display_name}
        </strong>
        <span>{STATUS_LABELS[introduction.status]}</span>
      </header>
      <p className="people-introduction-topic">{introduction.topic}</p>
      <p>{introduction.message}</p>
      {introduction.status === "accepted" ? (
        <p className="people-introduction-next">
          {outgoing
            ? `${introduction.other.display_name} agreed to help. Reach out in class or on the course channel.`
            : `You agreed to help ${introduction.other.display_name}.`}
        </p>
      ) : null}
      {actions.length ? (
        <span className="people-actions">
          {actions.map(([action, label]) => (
            <button disabled={busy} key={action} onClick={() => void act(action)} type="button">
              {label}
            </button>
          ))}
        </span>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </li>
  );
}

export function PeoplePanel() {
  const [overview, setOverview] = useState<PeopleOverview | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    void getMyPeople().then(
      (value) => {
        if (active) setOverview(value);
      },
      () => {
        if (active) setFailed(true);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  if (failed) {
    return <p className="workspace-panel-message">People is available to active students.</p>;
  }
  if (!overview) return <p className="workspace-panel-message">Loading…</p>;

  const pending = overview.introductions.filter(
    (item) => item.status === "draft" || (item.direction === "incoming" && item.status === "sent"),
  );
  const history = overview.introductions.filter((item) => !pending.includes(item));

  return (
    <div className="people-panel">
      {pending.length ? (
        <section aria-label="Introductions waiting for you">
          <h2>Waiting for you</h2>
          <ul>
            {pending.map((item) => (
              <IntroductionCard
                introduction={item}
                key={item.id}
                onUpdated={(introductions) => setOverview({ ...overview, introductions })}
              />
            ))}
          </ul>
        </section>
      ) : null}
      <section aria-label="What the Course Agent remembers about you">
        <h2>What the Course Agent remembers about you</h2>
        <p className="people-note">
          The agent uses these in every conversation with you. Only items set to “Classmates
          looking for help” can be shown to other students, and only when the agent looks for
          someone who can help them. Course staff have no view of this list.
        </p>
        {overview.memories.length ? (
          <ul>
            {overview.memories.map((memory) => (
              <MemoryCard
                key={memory.id}
                memory={memory}
                onChanged={(updated) =>
                  setOverview({
                    ...overview,
                    memories: overview.memories.map((item) =>
                      item.id === updated.id ? updated : item,
                    ),
                  })
                }
                onDeleted={(memoryId) =>
                  setOverview({
                    ...overview,
                    memories: overview.memories.filter((item) => item.id !== memoryId),
                  })
                }
              />
            ))}
          </ul>
        ) : (
          <p className="people-note">
            Nothing yet. Tell the agent about your background, project, or what you could help
            classmates with.
          </p>
        )}
      </section>
      {history.length ? (
        <section aria-label="Introductions">
          <h2>Introductions</h2>
          <ul>
            {history.map((item) => (
              <IntroductionCard
                introduction={item}
                key={item.id}
                onUpdated={(introductions) => setOverview({ ...overview, introductions })}
              />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
