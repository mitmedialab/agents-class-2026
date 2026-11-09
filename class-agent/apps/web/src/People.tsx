import { useEffect, useState } from "react";

import { Button } from "@class-agent/ui";

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

type IntroductionAction = "send" | "cancel" | "accept" | "decline";

// Match the server's REPLY_MAX_LENGTH and MESSAGE_MAX_LENGTH validation bounds.
const REPLY_MAX_LENGTH = 1000;
const MESSAGE_MAX_LENGTH = 2000;

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

// The three moments of an introduction, shown as a rail on open questions.
const STAGES = ["Drafted", "Sent", "Answered"] as const;

function stageIndex(status: PeerIntroduction["status"]): number {
  if (status === "draft") return 0;
  if (status === "sent") return 1;
  return 2;
}

function isOpen(item: PeerIntroduction): boolean {
  return item.status === "draft" || item.status === "sent";
}

function shortDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function actionsFor(item: PeerIntroduction): Array<[IntroductionAction, string]> {
  if (item.direction === "outgoing") {
    if (item.status === "draft") return [["send", "Send"], ["cancel", "Not now"]];
    if (item.status === "sent") return [["cancel", "Withdraw"]];
    return [];
  }
  return item.status === "sent" ? [["accept", "Accept"], ["decline", "Decline"]] : [];
}

/** Framing copy: belonging for the person asking, learning-by-teaching for the helper. */
function framingFor(item: PeerIntroduction): string | null {
  const name = item.other.display_name;
  if (item.direction === "outgoing" && item.status === "draft") {
    return `Getting stuck here is normal. ${name} was suggested because they shared that they can help. Edit the message in your own words; nothing is sent until you press Send.`;
  }
  if (item.direction === "outgoing" && item.status === "sent") {
    return `${name} can accept or decline. You will see their answer here.`;
  }
  if (item.direction === "incoming" && item.status === "sent") {
    return `Explaining something is one of the best ways to understand it yourself. If now is not a good time, ${name} will only see “Not available this time.”`;
  }
  return null;
}

function useIntroductionAction(
  introduction: PeerIntroduction,
  onUpdated: (introductions: PeerIntroduction[]) => void,
) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(action: IntroductionAction, text: { reply?: string; message?: string } = {}) {
    setBusy(true);
    setError(null);
    try {
      onUpdated((await actOnIntroduction(introduction.id, action, text)).introductions);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update this introduction.");
    } finally {
      setBusy(false);
    }
  }

  return { busy, error, act };
}

function StageRail({ status }: { status: PeerIntroduction["status"] }) {
  const current = stageIndex(status);
  return (
    <ol className="people-stages" aria-label="Progress">
      {STAGES.map((label, index) => (
        <li
          aria-current={index === current ? "step" : undefined}
          data-state={index < current ? "done" : index === current ? "current" : "upcoming"}
          key={label}
        >
          {label}
        </li>
      ))}
    </ol>
  );
}

function OpenQuestion({
  introduction,
  onUpdated,
}: {
  introduction: PeerIntroduction;
  onUpdated: (introductions: PeerIntroduction[]) => void;
}) {
  const { busy, error, act } = useIntroductionAction(introduction, onUpdated);
  const [reply, setReply] = useState("");
  const [message, setMessage] = useState(introduction.message);
  const outgoing = introduction.direction === "outgoing";
  const canReply = !outgoing && introduction.status === "sent";
  const editable = outgoing && introduction.status === "draft";
  const messageEdited = message.trim() !== introduction.message;

  function textFor(action: IntroductionAction): { reply?: string; message?: string } {
    if (action === "accept") return { reply };
    if (action === "send" && messageEdited) return { message: message.trim() };
    return {};
  }
  const name = introduction.other.display_name;
  const framing = framingFor(introduction);
  const actions = actionsFor(introduction);

  return (
    <article className="people-ask" data-direction={introduction.direction}>
      <p className="people-eyebrow">
        {outgoing ? "Your question" : "A classmate is asking you"}
        <span aria-hidden="true"> · </span>
        <span>{STATUS_LABELS[introduction.status]}</span>
      </p>
      <h3 className="people-ask-topic">{introduction.topic}</h3>
      <p className="people-route">
        <span>{outgoing ? "You" : name}</span>
        <span aria-hidden="true" className="people-route-rule" />
        <span className="visually-hidden">to</span>
        <span>{outgoing ? name : "You"}</span>
      </p>
      {editable ? (
        <textarea
          aria-label={`Message to ${name}`}
          className="people-letter people-letter-edit"
          maxLength={MESSAGE_MAX_LENGTH}
          onChange={(event) => setMessage(event.target.value)}
          rows={Math.min(10, Math.max(3, message.split("\n").length + 1))}
          value={message}
        />
      ) : (
        <blockquote className="people-letter">{introduction.message}</blockquote>
      )}
      <StageRail status={introduction.status} />
      {framing ? <p className="people-framing">{framing}</p> : null}
      {canReply ? (
        <label className="people-reply-field">
          <span className="people-eyebrow">Note to {name} (optional, sent if you accept)</span>
          <textarea
            maxLength={REPLY_MAX_LENGTH}
            onChange={(event) => setReply(event.target.value)}
            placeholder="Happy to help. I'm free after class on Thursday."
            rows={3}
            value={reply}
          />
        </label>
      ) : null}
      {actions.length ? (
        <div className="people-ask-actions">
          {actions.map(([action, label], index) => (
            <Button
              disabled={busy || (action === "send" && message.trim() === "")}
              key={action}
              onClick={() => void act(action, textFor(action))}
              variant={index === 0 ? "outline" : "plain"}
            >
              {label}
            </Button>
          ))}
        </div>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </article>
  );
}

function PastIntroduction({ introduction }: { introduction: PeerIntroduction }) {
  const outgoing = introduction.direction === "outgoing";
  const name = introduction.other.display_name;
  return (
    <li className="people-row people-past" data-status={introduction.status}>
      <span className="people-row-label">{STATUS_LABELS[introduction.status]}</span>
      <div className="people-row-body">
        <p className="people-past-topic">{introduction.topic}</p>
        <p className="people-meta">
          {outgoing ? `To ${name}` : `From ${name}`} · {shortDate(introduction.created_at)}
        </p>
        {introduction.status === "accepted" ? (
          <p className="people-past-next">
            {outgoing
              ? `${name} agreed to help. Reach out in class or on the course channel.`
              : `You agreed to help ${name}.`}
          </p>
        ) : null}
        {introduction.reply ? (
          <blockquote className="people-past-reply">
            <span className="visually-hidden">{outgoing ? `${name} wrote: ` : "You wrote: "}</span>
            {introduction.reply}
          </blockquote>
        ) : null}
      </div>
    </li>
  );
}

function MemoryRow({
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
    <li className="people-row people-memory" data-kind={memory.kind}>
      <span className="people-row-label">{KIND_LABELS[memory.kind]}</span>
      <div className="people-row-body">
        {editing ? (
          <textarea
            aria-label={`Edit ${KIND_LABELS[memory.kind].toLowerCase()} memory`}
            maxLength={500}
            onChange={(event) => setDraft(event.target.value)}
            rows={2}
            value={draft}
          />
        ) : (
          <p className="people-memory-content">{memory.content}</p>
        )}
        {memory.source_excerpt ? (
          <p className="people-meta" title="The message this memory came from">
            From your message: “{memory.source_excerpt}”
          </p>
        ) : null}
        <div className="people-memory-controls">
          <span className="people-meta">
            {memory.edited_by_student ? "Edited by you" : "Saved by the agent"} ·{" "}
            {shortDate(memory.updated_at)}
          </span>
          <label className="people-meta">
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
          <span className="people-memory-actions">
            {editing ? (
              <>
                <Button
                  disabled={busy || draft.trim() === ""}
                  onClick={() => void save({ content: draft })}
                >
                  Save
                </Button>
                <Button
                  disabled={busy}
                  onClick={() => {
                    setDraft(memory.content);
                    setEditing(false);
                  }}
                >
                  Cancel
                </Button>
              </>
            ) : (
              <Button disabled={busy} onClick={() => setEditing(true)}>
                Correct
              </Button>
            )}
            <Button disabled={busy} onClick={() => void remove()}>
              Forget
            </Button>
          </span>
        </div>
        {error ? <p role="alert">{error}</p> : null}
      </div>
    </li>
  );
}

function MemoryGroup({
  title,
  note,
  memories,
  onChanged,
  onDeleted,
}: {
  title: string;
  note: string;
  memories: StudentMemory[];
  onChanged: (memory: StudentMemory) => void;
  onDeleted: (memoryId: string) => void;
}) {
  if (!memories.length) return null;
  return (
    <div className="people-group">
      <h3 className="people-eyebrow">
        {title} <span className="people-count">{memories.length}</span>
      </h3>
      <p className="people-note">{note}</p>
      <ul className="people-rows">
        {memories.map((memory) => (
          <MemoryRow key={memory.id} memory={memory} onChanged={onChanged} onDeleted={onDeleted} />
        ))}
      </ul>
    </div>
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

  const open = overview.introductions.filter(isOpen);
  const past = overview.introductions.filter((item) => !isOpen(item));
  const shared = overview.memories.filter((item) => item.privacy === "course_private");
  const personal = overview.memories.filter((item) => item.privacy === "personal");

  const setIntroductions = (introductions: PeerIntroduction[]) =>
    setOverview({ ...overview, introductions });
  const changeMemory = (updated: StudentMemory) =>
    setOverview({
      ...overview,
      memories: overview.memories.map((item) => (item.id === updated.id ? updated : item)),
    });
  const deleteMemory = (memoryId: string) =>
    setOverview({
      ...overview,
      memories: overview.memories.filter((item) => item.id !== memoryId),
    });

  return (
    <div className="people-panel">
      <header className="people-intro">
        <p className="people-eyebrow">People</p>
        <h2>Learn with your classmates</h2>
        <p className="people-note">
          When you are stuck, the Course Agent can introduce you to a classmate who said they can
          help. When you know something, it can bring a classmate to you.
        </p>
      </header>

      {open.length ? (
        <section aria-label="Open questions" className="people-section">
          {open.map((item) => (
            <OpenQuestion introduction={item} key={item.id} onUpdated={setIntroductions} />
          ))}
        </section>
      ) : null}

      <section
        aria-label="What the Course Agent remembers about you"
        className="people-section"
      >
        <h2>What the Course Agent remembers about you</h2>
        <p className="people-note">
          The agent uses these in every conversation with you. Course staff have no view of this
          list.
        </p>
        {overview.memories.length ? (
          <>
            <MemoryGroup
              memories={shared}
              note="Shown to other students only when the agent looks for someone who can help them."
              onChanged={changeMemory}
              onDeleted={deleteMemory}
              title="Shared with classmates"
            />
            <MemoryGroup
              memories={personal}
              note="Used only in your own conversations."
              onChanged={changeMemory}
              onDeleted={deleteMemory}
              title="Only you"
            />
          </>
        ) : (
          <p className="people-note">
            Nothing yet. Tell the agent about your background, project, or what you could help
            classmates with.
          </p>
        )}
      </section>

      {past.length ? (
        <section aria-label="Introductions" className="people-section">
          <h2>Introductions</h2>
          <ul className="people-rows">
            {past.map((item) => (
              <PastIntroduction introduction={item} key={item.id} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
