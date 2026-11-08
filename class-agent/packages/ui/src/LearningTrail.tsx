import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { Button } from "./Button.js";
import { TextInput } from "./TextInput.js";

export interface LearningTrailFeedback {
  id: string;
  from_role: "instructor" | "ta";
  from_name?: string | null;
  body: string;
  received_at?: string | null;
  source: "pasted_by_student" | "staff";
  added_at: string;
}

export interface LearningTrailEntry {
  id: string;
  week: number;
  build_title: string;
  build_url?: string | null;
  reflection: string;
  topics: string[];
  still_relevant: boolean;
  shared_with_staff: boolean;
  shared_with_class: boolean;
  feedback: LearningTrailFeedback[];
  created_at: string;
  updated_at: string;
}

export interface LearningTrailEntryDraft {
  week: number;
  build_title: string;
  build_url: string | null;
  reflection: string;
  topics: string[];
  shared_with_staff: boolean;
  shared_with_class: boolean;
}

export interface LearningTrailTopic {
  id: string;
  title: string;
  week?: number | null;
}

export interface LearningTrailCoverage {
  practiced: LearningTrailTopic[];
  not_yet: LearningTrailTopic[];
}

/** An entry the agent drafted from a debrief. It is saved only when the student saves it. */
export interface LearningTrailPendingDraft {
  draft: LearningTrailEntryDraft;
  proposed_at: string;
}

export interface LearningTrailConnection {
  kind: "build" | "class" | "classmate";
  target_id: string;
  title: string;
  week?: number | null;
  url?: string | null;
  owner_name?: string | null;
  excerpt: string;
  score: number;
  shared_terms: string[];
}

export interface LearningTrailFeedbackDraft {
  from_role: "instructor" | "ta";
  from_name: string | null;
  body: string;
  received_at: string | null;
}

export interface LearningTrailStudent {
  student_id: string;
  student_name: string;
  shared_entries: number;
  latest_week: number;
}

export interface LearningTrailProps {
  /** Newest first, as the server orders them. */
  entries: LearningTrailEntry[];
  /** Keyed by entry ID, strongest first. */
  connections?: Record<string, LearningTrailConnection[]> | undefined;
  /** The course's topics, in week order, that a build can be tagged with. */
  topics?: LearningTrailTopic[] | undefined;
  /** An agent-drafted entry awaiting the student's decision. */
  pendingDraft?: LearningTrailPendingDraft | undefined;
  onAcceptDraft?: ((draft: LearningTrailEntryDraft) => Promise<void>) | undefined;
  onDiscardDraft?: (() => Promise<void>) | undefined;
  focusEntryId?: string | undefined;
  /** History views show what is saved now and do not allow changes. */
  readOnly?: boolean;
  onCreate: (draft: LearningTrailEntryDraft) => Promise<void>;
  onEdit: (entryId: string, draft: LearningTrailEntryDraft) => Promise<void>;
  onSetRelevant: (entryId: string, stillRelevant: boolean) => Promise<void>;
  onSetShared: (entryId: string, shared: boolean) => Promise<void>;
  onSetSharedWithClass: (entryId: string, shared: boolean) => Promise<void>;
  onDelete: (entryId: string) => Promise<void>;
  onAddFeedback: (entryId: string, draft: LearningTrailFeedbackDraft) => Promise<void>;
  onDeleteFeedback: (entryId: string, feedbackId: string) => Promise<void>;
  /** Sends a question to the Course Agent. Left out where asking is not possible. */
  onAsk?: ((message: string) => void) | undefined;
}

const SAVE_ERROR = "That could not be saved. Please try again.";

const FEEDBACK_ROLE_LABELS = { instructor: "Instructor", ta: "TA" } as const;

const NEXT_BUILD_QUESTION =
  "I'm starting my next build. Using my saved builds, what should I watch out for? " +
  "Tell me which weeks you drew on.";

function debriefQuestion(week: number): string {
  return (
    `I just finished my Week ${week} build. Debrief me: ask me three short questions one at a ` +
    "time, then draft my entry with the topics it practiced and open My builds so I can review it."
  );
}

function quizQuestion(entry: LearningTrailEntry): string {
  return (
    `Quiz me on my Week ${entry.week} build (${entry.build_title}): ask me one question about ` +
    "the most important lesson from my note or the feedback on it, wait for my answer, and only " +
    "then compare it with what I wrote and what staff said."
  );
}

function weekQuestion(entry: LearningTrailEntry): string {
  return (
    `What did I learn in Week ${entry.week} (${entry.build_title}), ` +
    "and how does it bear on what I'm working on now?"
  );
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  });
}

function EntryForm({
  draft,
  entry,
  initialWeek,
  onCancel,
  onSubmit,
  topics = [],
}: {
  /** Prefills the form from an agent-drafted entry; the student still saves it. */
  draft?: LearningTrailEntryDraft | undefined;
  entry?: LearningTrailEntry | undefined;
  initialWeek?: number | undefined;
  onCancel: () => void;
  onSubmit: (draft: LearningTrailEntryDraft) => Promise<void>;
  topics?: LearningTrailTopic[] | undefined;
}) {
  const source = entry ?? draft;
  const [week, setWeek] = useState(String(source?.week ?? initialWeek ?? ""));
  const [title, setTitle] = useState(source?.build_title ?? "");
  const [url, setUrl] = useState(source?.build_url ?? "");
  const [reflection, setReflection] = useState(source?.reflection ?? "");
  const [selectedTopics, setSelectedTopics] = useState<string[]>(source?.topics ?? []);
  const [shared, setShared] = useState(source?.shared_with_staff ?? true);
  const [sharedWithClass, setSharedWithClass] = useState(source?.shared_with_class ?? false);
  const fieldId = useId();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        week: Number(week),
        build_title: title,
        build_url: url.trim() || null,
        reflection,
        topics: selectedTopics,
        shared_with_staff: shared,
        shared_with_class: sharedWithClass,
      });
    } catch {
      setError(SAVE_ERROR);
      setSaving(false);
    }
  };

  return (
    <form
      aria-label={entry ? "Edit build" : draft ? "Review the drafted build" : "Add a build"}
      className="ca-trail-form"
      onSubmit={(event) => void submit(event)}
    >
      <div className="ca-trail-form-row">
        <TextInput
          id={`${fieldId}-week`}
          label="Week"
          max={20}
          min={1}
          onChange={(event) => setWeek(event.currentTarget.value)}
          required
          type="number"
          value={week}
        />
        <TextInput
          id={`${fieldId}-title`}
          label="What did you build?"
          maxLength={200}
          onChange={(event) => setTitle(event.currentTarget.value)}
          required
          value={title}
        />
      </div>
      <TextInput
        id={`${fieldId}-url`}
        label="Link (optional)"
        maxLength={2_048}
        onChange={(event) => setUrl(event.currentTarget.value)}
        pattern="https://.*"
        title="An https:// link to the build"
        type="url"
        value={url}
      />
      <label className="ca-field" htmlFor={`${fieldId}-reflection`}>
        <span className="ca-field__label">What did you learn, or what would you change?</span>
        <textarea
          className="ca-input ca-trail-textarea"
          id={`${fieldId}-reflection`}
          maxLength={20_000}
          onChange={(event) => setReflection(event.currentTarget.value)}
          required
          rows={8}
          value={reflection}
        />
      </label>
      {topics.length > 0 ? (
        <fieldset className="ca-trail-topics">
          <legend className="ca-field__label">Course topics this build practiced</legend>
          {topics.map((topic) => (
            <label className="ca-trail-relevant" key={topic.id}>
              <input
                checked={selectedTopics.includes(topic.id)}
                onChange={(event) =>
                  setSelectedTopics(
                    event.currentTarget.checked
                      ? [...selectedTopics, topic.id]
                      : selectedTopics.filter((id) => id !== topic.id),
                  )
                }
                type="checkbox"
              />
              {topic.week ? `Week ${topic.week} · ` : ""}
              {topic.title}
            </label>
          ))}
        </fieldset>
      ) : null}
      <label className="ca-trail-relevant">
        <input
          checked={shared}
          onChange={(event) => setShared(event.currentTarget.checked)}
          type="checkbox"
        />
        TAs can see this
      </label>
      <label className="ca-trail-relevant">
        <input
          checked={sharedWithClass}
          onChange={(event) => setSharedWithClass(event.currentTarget.checked)}
          type="checkbox"
        />
        Classmates can see this and your name
      </label>
      {error ? (
        <p className="ca-trail-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="ca-trail-actions">
        <Button className="ca-trail-action" disabled={saving} type="submit" variant="outline">
          Save
        </Button>
        <Button className="ca-trail-action" disabled={saving} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function FeedbackForm({
  onCancel,
  onSubmit,
}: {
  onCancel: () => void;
  onSubmit: (draft: LearningTrailFeedbackDraft) => Promise<void>;
}) {
  const [role, setRole] = useState<"instructor" | "ta">("ta");
  const [name, setName] = useState("");
  const [received, setReceived] = useState("");
  const [body, setBody] = useState("");
  const fieldId = useId();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        from_role: role,
        from_name: name.trim() || null,
        body,
        received_at: received ? `${received}T00:00:00Z` : null,
      });
    } catch {
      setError(SAVE_ERROR);
      setSaving(false);
    }
  };

  return (
    <form
      aria-label="Add feedback you received"
      className="ca-trail-form"
      onSubmit={(event) => void submit(event)}
    >
      <label className="ca-field" htmlFor={`${fieldId}-body`}>
        <span className="ca-field__label">Feedback, pasted from the email</span>
        <textarea
          className="ca-input ca-trail-textarea"
          id={`${fieldId}-body`}
          maxLength={10_000}
          onChange={(event) => setBody(event.currentTarget.value)}
          required
          rows={5}
          value={body}
        />
      </label>
      <div className="ca-trail-form-row">
        <label className="ca-field" htmlFor={`${fieldId}-role`}>
          <span className="ca-field__label">From</span>
          <select
            className="ca-input"
            id={`${fieldId}-role`}
            onChange={(event) =>
              setRole(event.currentTarget.value === "instructor" ? "instructor" : "ta")
            }
            value={role}
          >
            <option value="ta">TA</option>
            <option value="instructor">Instructor</option>
          </select>
        </label>
        <TextInput
          id={`${fieldId}-name`}
          label="Name (optional)"
          maxLength={200}
          onChange={(event) => setName(event.currentTarget.value)}
          value={name}
        />
        <TextInput
          id={`${fieldId}-date`}
          label="Received (optional)"
          onChange={(event) => setReceived(event.currentTarget.value)}
          type="date"
          value={received}
        />
      </div>
      {error ? (
        <p className="ca-trail-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="ca-trail-actions">
        <Button className="ca-trail-action" disabled={saving} type="submit" variant="outline">
          Save feedback
        </Button>
        <Button className="ca-trail-action" disabled={saving} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function EntryFeedback({
  canRemove,
  entry,
  onRemove,
  pastedLabel,
}: {
  canRemove?: (feedback: LearningTrailFeedback) => boolean;
  entry: LearningTrailEntry;
  onRemove?: (feedbackId: string) => void;
  pastedLabel: string;
}) {
  if (entry.feedback.length === 0) return null;
  return (
    <section aria-label={`Feedback on ${entry.build_title}`} className="ca-trail-feedback">
      {entry.feedback.map((feedback) => (
        <div className="ca-trail-feedback-item" key={feedback.id}>
          <p className="ca-trail-kicker">
            {FEEDBACK_ROLE_LABELS[feedback.from_role]}
            {feedback.from_name ? ` · ${feedback.from_name}` : ""}
            {feedback.received_at ? ` · ${formatDate(feedback.received_at)}` : ""}
            {feedback.source === "pasted_by_student" ? ` · ${pastedLabel}` : ""}
          </p>
          <p className="ca-trail-text">{feedback.body}</p>
          {onRemove && canRemove?.(feedback) ? (
            <Button
              aria-label={`Remove feedback from ${FEEDBACK_ROLE_LABELS[feedback.from_role]}`}
              className="ca-trail-action"
              onClick={() => onRemove(feedback.id)}
            >
              Remove
            </Button>
          ) : null}
        </div>
      ))}
    </section>
  );
}

function EntryDetails({
  entry,
  onAddFeedback,
  onAsk,
  onCollapse,
  onDelete,
  onDeleteFeedback,
  onEdit,
  onSetRelevant,
  onSetShared,
  onSetSharedWithClass,
  readOnly,
  topics,
}: {
  entry: LearningTrailEntry;
  onCollapse: () => void;
  readOnly: boolean;
  topics: LearningTrailTopic[];
} & Pick<
  LearningTrailProps,
  | "onAddFeedback"
  | "onAsk"
  | "onDelete"
  | "onDeleteFeedback"
  | "onEdit"
  | "onSetRelevant"
  | "onSetShared"
  | "onSetSharedWithClass"
>) {
  const [mode, setMode] = useState<"read" | "edit" | "feedback">("read");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const attempt = async (action: () => Promise<void>) => {
    setError(null);
    try {
      await action();
    } catch {
      setError(SAVE_ERROR);
    }
  };

  if (mode === "edit") {
    return (
      <EntryForm
        entry={entry}
        onCancel={() => setMode("read")}
        onSubmit={async (draft) => {
          await onEdit(entry.id, draft);
          setMode("read");
        }}
        topics={topics}
      />
    );
  }

  return (
    <div className="ca-trail-entry">
      <p className="ca-trail-text">{entry.reflection}</p>
      {entry.topics.length > 0 ? (
        <p className="ca-trail-topic-tags">
          {entry.topics.map((id) => (
            <span key={id}>{topics.find((topic) => topic.id === id)?.title ?? id}</span>
          ))}
        </p>
      ) : null}
      {entry.build_url ? (
        <a className="ca-trail-link" href={entry.build_url} rel="noreferrer" target="_blank">
          Open the build
        </a>
      ) : null}
      <EntryFeedback
        entry={entry}
        pastedLabel="Pasted by you"
        {...(readOnly
          ? {}
          : {
              canRemove: (feedback: LearningTrailFeedback) => feedback.source !== "staff",
              onRemove: (feedbackId: string) =>
                void attempt(() => onDeleteFeedback(entry.id, feedbackId)),
            })}
      />
      {mode === "feedback" ? (
        <FeedbackForm
          onCancel={() => setMode("read")}
          onSubmit={async (draft) => {
            await onAddFeedback(entry.id, draft);
            setMode("read");
          }}
        />
      ) : null}
      {error ? (
        <p className="ca-trail-error" role="alert">
          {error}
        </p>
      ) : null}
      {readOnly || mode === "feedback" ? null : (
        <>
          <div className="ca-trail-toggles">
            <label
              className="ca-trail-toggle"
              title="Turn off to keep the note here without it affecting the agent's help."
            >
              <input
                checked={entry.still_relevant}
                onChange={(event) => {
                  const stillRelevant = event.currentTarget.checked;
                  void attempt(() => onSetRelevant(entry.id, stillRelevant));
                }}
                type="checkbox"
              />
              Agent can use this
            </label>
            <label
              className="ca-trail-toggle"
              title="A TA or instructor can read it and comment."
            >
              <input
                checked={entry.shared_with_staff}
                onChange={(event) => {
                  const shared = event.currentTarget.checked;
                  void attempt(() => onSetShared(entry.id, shared));
                }}
                type="checkbox"
              />
              TAs can see this
            </label>
            <label
              className="ca-trail-toggle"
              title="Classmates see your name, title, link, and a short excerpt. Feedback stays private."
            >
              <input
                checked={entry.shared_with_class}
                onChange={(event) => {
                  const shared = event.currentTarget.checked;
                  void attempt(() => onSetSharedWithClass(entry.id, shared));
                }}
                type="checkbox"
              />
              Classmates can see this
            </label>
          </div>
          <div className="ca-trail-actions">
            {onAsk ? (
              <>
                <Button className="ca-trail-action" onClick={() => onAsk(quizQuestion(entry))}>
                  Check what stuck
                </Button>
                <Button className="ca-trail-action" onClick={() => onAsk(weekQuestion(entry))}>
                  Ask about this week
                </Button>
              </>
            ) : null}
            <Button className="ca-trail-action" onClick={() => setMode("feedback")}>
              Add feedback
            </Button>
            <Button className="ca-trail-action" onClick={() => setMode("edit")}>
              Edit
            </Button>
            {confirmingDelete ? (
              <>
                <Button
                  className="ca-trail-action"
                  onClick={() => void attempt(() => onDelete(entry.id))}
                  variant="outline"
                >
                  Confirm delete
                </Button>
                <Button className="ca-trail-action" onClick={() => setConfirmingDelete(false)}>
                  Keep
                </Button>
              </>
            ) : (
              <Button className="ca-trail-action" onClick={() => setConfirmingDelete(true)}>
                Delete
              </Button>
            )}
          </div>
        </>
      )}
      <div className="ca-trail-actions ca-trail-entry-end">
        <Button
          className="ca-trail-action ca-trail-jump"
          onClick={() =>
            document
              .getElementById("ca-trail-connections")
              ?.scrollIntoView?.({ behavior: "smooth", block: "start" })
          }
        >
          See connections
        </Button>
        <Button className="ca-trail-action" onClick={onCollapse}>
          Collapse
        </Button>
      </div>
    </div>
  );
}

/** Rows show only what departs from the usual, so a plain row means "the agent uses it". */
function entryStatus(entry: LearningTrailEntry): string | null {
  const feedback = entry.feedback.length;
  const notes = [
    ...(entry.still_relevant ? [] : ["Not used by the agent"]),
    ...(feedback > 0 ? [`${feedback} feedback`] : []),
  ];
  return notes.length > 0 ? notes.join(" · ") : null;
}

const CONNECTION_GROUPS = [
  { kind: "build", label: "Your builds" },
  { kind: "class", label: "Class slides and readings" },
  { kind: "classmate", label: "Classmates" },
] as const;

const MAP_NODE_LIMIT = 12;

/** Stronger connections sit closer to the centre. Angles spread by the golden angle. */
function mapPosition(index: number, score: number, lowest: number, highest: number) {
  const strength = highest > lowest ? (score - lowest) / (highest - lowest) : 1;
  const radius = 42 - 24 * strength;
  const angle = ((index * 137.508 - 90) * Math.PI) / 180;
  return { left: 50 + radius * Math.cos(angle), top: 50 + radius * 0.86 * Math.sin(angle) };
}

function connectionPlace(connection: LearningTrailConnection): string | null {
  const week = connection.week ? `Week ${connection.week}` : null;
  if (connection.kind === "classmate") {
    return [connection.owner_name, week].filter(Boolean).join(" · ") || null;
  }
  return connection.kind === "build" ? week : null;
}

function ConnectionMap({
  connections,
  highlightedId,
  onHighlight,
  onOpen,
}: {
  connections: LearningTrailConnection[];
  highlightedId: string | undefined;
  onHighlight: (id: string | undefined) => void;
  onOpen: (connection: LearningTrailConnection) => void;
}) {
  const shown = connections.slice(0, MAP_NODE_LIMIT);
  const scores = shown.map((connection) => connection.score);
  const highest = Math.max(...scores);
  const lowest = Math.min(...scores);
  const nodes = shown.map((connection, index) => ({
    connection,
    ...mapPosition(index, connection.score, lowest, highest),
  }));
  const highlighted = shown.find(({ target_id }) => target_id === highlightedId);
  const place = highlighted ? connectionPlace(highlighted) : null;

  return (
    <div className="ca-trail-map" onMouseLeave={() => onHighlight(undefined)}>
      <svg aria-hidden="true" preserveAspectRatio="none" viewBox="0 0 100 100">
        {nodes.map(({ connection, left, top }) => (
          <line
            data-active={connection.target_id === highlightedId}
            key={connection.target_id}
            vectorEffect="non-scaling-stroke"
            x1="50"
            x2={left}
            y1="50"
            y2={top}
          />
        ))}
      </svg>
      <span aria-hidden="true" className="ca-trail-map-center" />
      {nodes.map(({ connection, left, top }) => (
        <button
          aria-label={`Show ${connection.title}`}
          className="ca-trail-map-node"
          data-active={connection.target_id === highlightedId}
          data-kind={connection.kind}
          key={connection.target_id}
          onClick={() => onOpen(connection)}
          onFocus={() => onHighlight(connection.target_id)}
          onMouseEnter={() => onHighlight(connection.target_id)}
          style={{ left: `${left}%`, top: `${top}%` }}
          type="button"
        >
          <span aria-hidden="true" className="ca-trail-map-mark" />
        </button>
      ))}
      <p aria-hidden="true" className="ca-trail-map-caption">
        {highlighted ? [place, highlighted.title].filter(Boolean).join(" · ") : " "}
      </p>
    </div>
  );
}

/** The open learner model: which course topics each saved build practiced, and the gaps. */
function SkillsMap({
  entries,
  onSelectBuild,
  selectedEntryId,
  topics,
}: {
  entries: LearningTrailEntry[];
  onSelectBuild: (entryId: string) => void;
  selectedEntryId: string | undefined;
  topics: LearningTrailTopic[];
}) {
  const builds = [...entries].sort((a, b) => a.week - b.week);
  const practiced = new Set(
    builds.filter((entry) => entry.still_relevant).flatMap((entry) => entry.topics),
  );
  const untouched = topics.filter((topic) => !practiced.has(topic.id));
  const tagged = builds.some((entry) => entry.topics.length > 0);

  return (
    <section aria-label="Skills map" className="ca-trail-skills">
      <h3>What your builds have practiced</h3>
      {tagged ? (
        <table className="ca-trail-skills-grid">
          <thead>
            <tr>
              <th scope="col">
                <span className="ca-visually-hidden">Topic</span>
              </th>
              {builds.map((entry) => (
                <th key={entry.id} scope="col">
                  <button
                    aria-label={`Week ${entry.week}: ${entry.build_title}`}
                    aria-pressed={entry.id === selectedEntryId}
                    onClick={() => onSelectBuild(entry.id)}
                    title={entry.build_title}
                    type="button"
                  >
                    W{entry.week}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {topics.map((topic) => (
              <tr data-practiced={practiced.has(topic.id)} key={topic.id}>
                <th scope="row">{topic.title}</th>
                {builds.map((entry) => {
                  const hit = entry.topics.includes(topic.id);
                  const feedback = hit && entry.feedback.length > 0;
                  return (
                    <td
                      aria-label={
                        hit
                          ? `Practiced in Week ${entry.week}${feedback ? ", with feedback" : ""}`
                          : undefined
                      }
                      data-feedback={feedback}
                      data-hit={hit}
                      data-unused={hit && !entry.still_relevant}
                      key={entry.id}
                    >
                      <span aria-hidden="true" />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="ca-trail-note">
          Tag each build with the course topics it practiced, and this map fills in. A debrief
          suggests the tags for you.
        </p>
      )}
      {tagged && untouched.length > 0 ? (
        <p className="ca-trail-skills-gaps">
          Not yet in any build: {untouched.map((topic) => topic.title).join(", ")}.
        </p>
      ) : null}
    </section>
  );
}

function ConnectionsPanel({
  connections,
  entry,
  onAsk,
  onSelectBuild,
}: {
  connections: LearningTrailConnection[] | undefined;
  entry: LearningTrailEntry;
  onAsk: ((message: string) => void) | undefined;
  onSelectBuild: (entryId: string) => void;
}) {
  const [openId, setOpenId] = useState<string | undefined>();
  const [highlightedId, setHighlightedId] = useState<string | undefined>();
  const [mapShown, setMapShown] = useState(true);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setOpenId(undefined);
    setHighlightedId(undefined);
  }, [entry.id]);

  useEffect(() => {
    if (openId === undefined) return;
    const row = listRef.current?.querySelector(`[data-connection-id="${CSS.escape(openId)}"]`);
    row?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [openId]);

  const hasConnections = connections !== undefined && connections.length > 0;

  return (
    <aside
      aria-label={`Connections for ${entry.build_title}`}
      className="ca-trail-connections"
      id="ca-trail-connections"
    >
      <header className="ca-trail-connections-header">
        <h3>Week {entry.week} connects to</h3>
        {hasConnections ? (
          <Button
            aria-expanded={mapShown}
            className="ca-trail-action"
            onClick={() => setMapShown(!mapShown)}
          >
            {mapShown ? "Hide map" : "Show map"}
          </Button>
        ) : null}
      </header>
      {connections === undefined ? (
        <p className="ca-trail-note">Finding connections…</p>
      ) : connections.length === 0 ? (
        <p className="ca-trail-note">
          Nothing yet. Connections come from the words in your notes, so longer notes find more.
        </p>
      ) : (
        <>
          {mapShown ? (
            <ConnectionMap
              connections={connections}
              highlightedId={highlightedId}
              onHighlight={setHighlightedId}
              onOpen={(connection) => {
                setOpenId(connection.target_id);
                setHighlightedId(connection.target_id);
              }}
            />
          ) : null}
          <div className="ca-trail-connection-groups" ref={listRef}>
            {CONNECTION_GROUPS.map(({ kind, label }) => {
              const items = connections.filter((connection) => connection.kind === kind);
              if (items.length === 0) return null;
              return (
                <section aria-label={label} className="ca-trail-connection-group" key={kind}>
                  <h4 data-kind={kind}>{label}</h4>
                  <ol className="ca-trail-connection-list">
                    {items.map((connection) => (
                      <ConnectionRow
                        connection={connection}
                        entry={entry}
                        highlighted={highlightedId === connection.target_id}
                        isOpen={openId === connection.target_id}
                        key={connection.target_id}
                        onAsk={onAsk}
                        onHighlight={setHighlightedId}
                        onSelectBuild={onSelectBuild}
                        onToggle={() =>
                          setOpenId(openId === connection.target_id ? undefined : connection.target_id)
                        }
                      />
                    ))}
                  </ol>
                </section>
              );
            })}
          </div>
        </>
      )}
    </aside>
  );
}

function ConnectionRow({
  connection,
  entry,
  highlighted,
  isOpen,
  onAsk,
  onHighlight,
  onSelectBuild,
  onToggle,
}: {
  connection: LearningTrailConnection;
  entry: LearningTrailEntry;
  highlighted: boolean;
  isOpen: boolean;
  onAsk: ((message: string) => void) | undefined;
  onHighlight: (id: string | undefined) => void;
  onSelectBuild: (entryId: string) => void;
  onToggle: () => void;
}) {
  const place = connectionPlace(connection);
  return (
    <li
      data-active={highlighted}
      data-connection-id={connection.target_id}
      data-open={isOpen}
      onMouseEnter={() => onHighlight(connection.target_id)}
    >
      <button
        aria-expanded={isOpen}
        className="ca-trail-connection-row"
        onClick={onToggle}
        type="button"
      >
        <span className="ca-trail-connection-title">{connection.title}</span>
        {place ? <span className="ca-trail-connection-place">{place}</span> : null}
        <span aria-hidden="true" className="ca-trail-chevron" data-open={isOpen} />
      </button>
      {isOpen ? (
        <div className="ca-trail-connection-details">
          <p className="ca-trail-excerpt-full">{connection.excerpt}</p>
          {connection.shared_terms.length > 0 ? (
            <p className="ca-trail-status">Shared words: {connection.shared_terms.join(", ")}</p>
          ) : null}
          <div className="ca-trail-actions">
            {connection.url ? (
              <a className="ca-trail-link" href={connection.url} rel="noreferrer" target="_blank">
                Open the build
              </a>
            ) : null}
            {connection.kind === "build" ? (
              <Button
                className="ca-trail-action"
                onClick={() => onSelectBuild(connection.target_id)}
              >
                Show its connections
              </Button>
            ) : null}
            {connection.kind === "class" && onAsk ? (
              <Button
                className="ca-trail-action"
                onClick={() => onAsk(`Open ${connection.target_id} for me.`)}
              >
                Open in chat
              </Button>
            ) : null}
            {connection.kind !== "classmate" && onAsk ? (
              <Button
                className="ca-trail-action"
                onClick={() => onAsk(connectionQuestion(entry, connection))}
              >
                Ask how they connect
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </li>
  );
}

function connectionQuestion(
  entry: LearningTrailEntry,
  connection: LearningTrailConnection,
): string {
  const target =
    connection.kind === "build"
      ? `my Week ${connection.week} build (${connection.title})`
      : `the class material "${connection.title}" (${connection.target_id})`;
  return `How does my Week ${entry.week} build (${entry.build_title}) connect to ${target}?`;
}

export function LearningTrail({
  connections,
  entries,
  focusEntryId,
  onAcceptDraft,
  onAsk,
  onCreate,
  onDiscardDraft,
  pendingDraft,
  readOnly = false,
  topics = [],
  ...entryActions
}: LearningTrailProps) {
  const [composingWeek, setComposingWeek] = useState<number | null>(null);
  const [openEntryId, setOpenEntryId] = useState<string | undefined>(focusEntryId);
  const [selectedEntryId, setSelectedEntryId] = useState<string | undefined>(focusEntryId);
  const weeksRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    // Follow the agent when it points at another entry; a later save must not move the reader.
    if (focusEntryId !== undefined) {
      setOpenEntryId(focusEntryId);
      setSelectedEntryId(focusEntryId);
    }
  }, [focusEntryId]);

  useEffect(() => {
    // Opening a build closes the one before it, so bring the new one into view.
    if (openEntryId === undefined) return;
    const row = weeksRef.current?.querySelector(`[data-entry-id="${CSS.escape(openEntryId)}"]`);
    row?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [openEntryId]);

  const latestWeek = entries.reduce((latest, entry) => Math.max(latest, entry.week), 0);
  const savedWeeks = new Set(entries.map((entry) => entry.week));
  const missingWeeks = Array.from({ length: latestWeek }, (_, index) => index + 1).filter(
    (week) => !savedWeeks.has(week),
  );
  const rows = [
    ...entries.map((entry) => ({ week: entry.week, entry })),
    ...missingWeeks.map((week) => ({ week, entry: undefined })),
  ].sort((a, b) => b.week - a.week);
  const selectedEntry =
    entries.find((entry) => entry.id === selectedEntryId) ?? entries[0];

  const toggleRow = (entryId: string) => {
    setSelectedEntryId(entryId);
    setOpenEntryId(openEntryId === entryId ? undefined : entryId);
  };

  return (
    <section aria-label="Learning trail" className="ca-learning-trail">
      <header className="ca-trail-header">
        <h2>My builds</h2>
        {readOnly ? null : (
          <div className="ca-trail-actions">
            <Button
              className="ca-trail-action"
              onClick={() => setComposingWeek(latestWeek + 1)}
              variant={entries.length === 0 ? "outline" : "plain"}
            >
              Add a build
            </Button>
            {onAsk ? (
              <Button
                className="ca-trail-action"
                onClick={() => onAsk(debriefQuestion(latestWeek + 1))}
                variant="outline"
              >
                Debrief this week with the agent
              </Button>
            ) : null}
            {onAsk && entries.length > 0 ? (
              <Button className="ca-trail-action" onClick={() => onAsk(NEXT_BUILD_QUESTION)}>
                Ask about my next build
              </Button>
            ) : null}
          </div>
        )}
      {pendingDraft && onAcceptDraft && !readOnly ? (
        <section aria-label="Drafted from your debrief" className="ca-trail-draft">
          <p className="ca-trail-note">
            The agent drafted this from your debrief. Nothing is saved yet: change anything, then
            save it, or discard it.
          </p>
          <EntryForm
            draft={pendingDraft.draft}
            key={pendingDraft.proposed_at}
            onCancel={() => void onDiscardDraft?.()}
            onSubmit={onAcceptDraft}
            topics={topics}
          />
        </section>
      ) : null}
      </header>
      {composingWeek !== null ? (
        <EntryForm
          initialWeek={composingWeek}
          key={composingWeek}
          onCancel={() => setComposingWeek(null)}
          onSubmit={async (draft) => {
            await onCreate(draft);
            setComposingWeek(null);
          }}
          topics={topics}
        />
      ) : null}
      {rows.length > 0 ? (
        <div className="ca-trail-columns">
          <div className="ca-trail-column">
            <ol className="ca-trail-weeks" ref={weeksRef}>
              {rows.map(({ week, entry }) => {
                if (entry === undefined) {
                  return (
                    <li data-state="empty" key={`week-${week}`}>
                      <div className="ca-trail-row ca-trail-row--empty">
                        <span className="ca-trail-row-week">Week {week}</span>
                        {readOnly ? (
                          <span className="ca-trail-row-body">Nothing saved</span>
                        ) : (
                          <Button
                            aria-label={`Add a build for Week ${week}`}
                            className="ca-trail-action ca-trail-row-body"
                            onClick={() => setComposingWeek(week)}
                          >
                            Add a build
                          </Button>
                        )}
                      </div>
                    </li>
                  );
                }
                const isOpen = openEntryId === entry.id;
                const status = entryStatus(entry);
                return (
                  <li
                    data-entry-id={entry.id}
                    data-open={isOpen}
                    data-selected={entry.id === selectedEntry?.id}
                    data-state={entry.still_relevant ? "used" : "unused"}
                    key={entry.id}
                  >
                    <button
                      aria-expanded={isOpen}
                      className="ca-trail-row"
                      onClick={() => toggleRow(entry.id)}
                      type="button"
                    >
                      <span className="ca-trail-row-week">Week {entry.week}</span>
                      <span className="ca-trail-row-body">
                        <span className="ca-trail-row-title">{entry.build_title}</span>
                        {isOpen ? null : (
                          <span className="ca-trail-excerpt">{entry.reflection}</span>
                        )}
                        {status ? <span className="ca-trail-status">{status}</span> : null}
                      </span>
                      <span aria-hidden="true" className="ca-trail-chevron" data-open={isOpen} />
                    </button>
                    {isOpen ? (
                      <EntryDetails
                        entry={entry}
                        onAsk={onAsk}
                        onCollapse={() => setOpenEntryId(undefined)}
                        readOnly={readOnly}
                        topics={topics}
                        {...entryActions}
                      />
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </div>
          {selectedEntry ? (
            <div className="ca-trail-column">
              {topics.length > 0 ? (
                <SkillsMap
                  entries={entries}
                  onSelectBuild={(entryId) => {
                    setSelectedEntryId(entryId);
                    setOpenEntryId(entryId);
                  }}
                  selectedEntryId={selectedEntry.id}
                  topics={topics}
                />
              ) : null}
              <ConnectionsPanel
                connections={connections?.[selectedEntry.id]}
                entry={selectedEntry}
                onAsk={onAsk}
                onSelectBuild={(entryId) => {
                  setSelectedEntryId(entryId);
                  setOpenEntryId(entryId);
                }}
              />
            </div>
          ) : null}
        </div>
      ) : composingWeek !== null ? null : (
        <p className="ca-trail-note">Nothing saved yet. Start with the build you did last.</p>
      )}
    </section>
  );
}

export interface LearningTrailStaffProps {
  students: LearningTrailStudent[];
  selectedStudent?: LearningTrailStudent | undefined;
  entries: LearningTrailEntry[];
  readOnly?: boolean;
  onSelectStudent: (student: LearningTrailStudent | undefined) => void;
  onAddFeedback: (entryId: string, body: string) => Promise<void>;
  onDeleteFeedback: (entryId: string, feedbackId: string) => Promise<void>;
}

function StaffEntry({
  entry,
  onAddFeedback,
  onDeleteFeedback,
  readOnly,
}: {
  entry: LearningTrailEntry;
  readOnly: boolean;
} & Pick<LearningTrailStaffProps, "onAddFeedback" | "onDeleteFeedback">) {
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fieldId = useId();

  const attempt = async (action: () => Promise<void>) => {
    setSaving(true);
    setError(null);
    try {
      await action();
    } catch {
      setError(SAVE_ERROR);
    } finally {
      setSaving(false);
    }
  };

  return (
    <article className="ca-trail-entry" data-set-aside={!entry.still_relevant}>
      <header className="ca-trail-entry-header">
        <p className="ca-trail-kicker">
          Week {entry.week}
          {entry.still_relevant ? null : " · The student's agent does not use this"}
        </p>
        <h3>
          {entry.build_url ? (
            <a href={entry.build_url} rel="noreferrer" target="_blank">
              {entry.build_title}
            </a>
          ) : (
            entry.build_title
          )}
        </h3>
      </header>
      <p className="ca-trail-text">{entry.reflection}</p>
      <EntryFeedback
        entry={entry}
        pastedLabel="Pasted by student"
        {...(readOnly
          ? {}
          : {
              canRemove: (feedback: LearningTrailFeedback) => feedback.source === "staff",
              onRemove: (feedbackId: string) =>
                void attempt(() => onDeleteFeedback(entry.id, feedbackId)),
            })}
      />
      {readOnly ? null : (
        <form
          aria-label={`Write feedback on ${entry.build_title}`}
          className="ca-trail-form"
          onSubmit={(event) => {
            event.preventDefault();
            void attempt(async () => {
              await onAddFeedback(entry.id, body);
              setBody("");
            });
          }}
        >
          <label className="ca-field" htmlFor={`${fieldId}-body`}>
            <span className="ca-field__label">Write feedback</span>
            <textarea
              className="ca-input ca-trail-textarea"
              id={`${fieldId}-body`}
              maxLength={10_000}
              onChange={(event) => setBody(event.currentTarget.value)}
              required
              rows={4}
              value={body}
            />
          </label>
          <div className="ca-trail-actions">
            <Button className="ca-trail-action" disabled={saving} type="submit" variant="outline">
              Send to student
            </Button>
          </div>
        </form>
      )}
      {error ? (
        <p className="ca-trail-error" role="alert">
          {error}
        </p>
      ) : null}
    </article>
  );
}

export function LearningTrailStaff({
  entries,
  onAddFeedback,
  onDeleteFeedback,
  onSelectStudent,
  readOnly = false,
  selectedStudent,
  students,
}: LearningTrailStaffProps) {
  return (
    <section aria-label="Learning trails" className="ca-learning-trail">
      <header className="ca-trail-header">
        <p className="ca-trail-kicker">Learning trail</p>
        <h2>{selectedStudent ? selectedStudent.student_name : "Student builds"}</h2>
        <p className="ca-trail-note">
          Only builds students chose to share appear here. Students see your feedback beside their
          notes, and the Course Agent can draw on it when helping them later.
        </p>
        {selectedStudent ? (
          <div className="ca-trail-actions">
            <Button className="ca-trail-action" onClick={() => onSelectStudent(undefined)}>
              All students
            </Button>
          </div>
        ) : null}
      </header>
      {selectedStudent ? (
        entries.length > 0 ? (
          entries.map((entry) => (
            <StaffEntry
              entry={entry}
              key={entry.id}
              onAddFeedback={onAddFeedback}
              onDeleteFeedback={onDeleteFeedback}
              readOnly={readOnly}
            />
          ))
        ) : (
          <p className="ca-trail-note">This student has no shared builds right now.</p>
        )
      ) : students.length > 0 ? (
        <ol className="ca-trail-students">
          {students.map((student) => (
            <li key={student.student_id}>
              <button
                className="ca-trail-row ca-trail-student-row"
                onClick={() => onSelectStudent(student)}
                type="button"
              >
                <span>{student.student_name}</span>
                <span className="ca-trail-kicker">
                  {student.shared_entries} shared · through week {student.latest_week}
                </span>
              </button>
            </li>
          ))}
        </ol>
      ) : (
        <p className="ca-trail-note">No student has shared a build yet.</p>
      )}
    </section>
  );
}
