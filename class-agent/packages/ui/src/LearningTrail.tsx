import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { Button } from "./Button.js";
import { TextInput } from "./TextInput.js";

export interface LearningTrailFeedback {
  id: string;
  from_role: "instructor" | "ta";
  from_name?: string | null;
  body: string;
  received_at?: string | null;
  source: "pasted_by_student";
  added_at: string;
}

export interface LearningTrailEntry {
  id: string;
  week: number;
  build_title: string;
  build_url?: string | null;
  reflection: string;
  still_relevant: boolean;
  feedback: LearningTrailFeedback[];
  created_at: string;
  updated_at: string;
}

export interface LearningTrailEntryDraft {
  week: number;
  build_title: string;
  build_url: string | null;
  reflection: string;
}

export interface LearningTrailFeedbackDraft {
  from_role: "instructor" | "ta";
  from_name: string | null;
  body: string;
  received_at: string | null;
}

export interface LearningTrailProps {
  /** Newest first, as the server orders them. */
  entries: LearningTrailEntry[];
  focusEntryId?: string | undefined;
  /** History views show what is saved now and do not allow changes. */
  readOnly?: boolean;
  onCreate: (draft: LearningTrailEntryDraft) => Promise<void>;
  onEdit: (entryId: string, draft: LearningTrailEntryDraft) => Promise<void>;
  onSetRelevant: (entryId: string, stillRelevant: boolean) => Promise<void>;
  onDelete: (entryId: string) => Promise<void>;
  onAddFeedback: (entryId: string, draft: LearningTrailFeedbackDraft) => Promise<void>;
  onDeleteFeedback: (entryId: string, feedbackId: string) => Promise<void>;
}

const SAVE_ERROR = "That could not be saved. Please try again.";

const FEEDBACK_ROLE_LABELS = { instructor: "Instructor", ta: "TA" } as const;

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  });
}

function EntryForm({
  entry,
  onCancel,
  onSubmit,
}: {
  entry?: LearningTrailEntry | undefined;
  onCancel: () => void;
  onSubmit: (draft: LearningTrailEntryDraft) => Promise<void>;
}) {
  const [week, setWeek] = useState(entry ? String(entry.week) : "");
  const [title, setTitle] = useState(entry?.build_title ?? "");
  const [url, setUrl] = useState(entry?.build_url ?? "");
  const [reflection, setReflection] = useState(entry?.reflection ?? "");
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
      });
    } catch {
      setError(SAVE_ERROR);
      setSaving(false);
    }
  };

  return (
    <form
      aria-label={entry ? "Edit reflection" : "New reflection"}
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
          label="Build"
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
        <span className="ca-field__label">Reflection</span>
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
      aria-label="Add feedback"
      className="ca-trail-form"
      onSubmit={(event) => void submit(event)}
    >
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
      {error ? (
        <p className="ca-trail-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="ca-trail-actions">
        <Button className="ca-trail-action" disabled={saving} type="submit" variant="outline">
          Attach
        </Button>
        <Button className="ca-trail-action" disabled={saving} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function Entry({
  entry,
  onAddFeedback,
  onDelete,
  onDeleteFeedback,
  onEdit,
  onSetRelevant,
  readOnly,
}: {
  entry: LearningTrailEntry;
  readOnly: boolean;
} & Pick<
  LearningTrailProps,
  "onAddFeedback" | "onDelete" | "onDeleteFeedback" | "onEdit" | "onSetRelevant"
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
      />
    );
  }

  return (
    <article className="ca-trail-entry" data-set-aside={!entry.still_relevant}>
      <header className="ca-trail-entry-header">
        <p className="ca-trail-kicker">
          Week {entry.week}
          {entry.still_relevant ? null : " · Set aside"}
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
      {entry.feedback.length > 0 ? (
        <section aria-label={`Feedback on ${entry.build_title}`} className="ca-trail-feedback">
          {entry.feedback.map((feedback) => (
            <div className="ca-trail-feedback-item" key={feedback.id}>
              <p className="ca-trail-kicker">
                {FEEDBACK_ROLE_LABELS[feedback.from_role]}
                {feedback.from_name ? ` · ${feedback.from_name}` : ""}
                {feedback.received_at ? ` · ${formatDate(feedback.received_at)}` : ""}
                {" · Pasted by you"}
              </p>
              <p className="ca-trail-text">{feedback.body}</p>
              {readOnly ? null : (
                <Button
                  aria-label={`Remove feedback from ${FEEDBACK_ROLE_LABELS[feedback.from_role]}`}
                  className="ca-trail-action"
                  onClick={() => void attempt(() => onDeleteFeedback(entry.id, feedback.id))}
                >
                  Remove
                </Button>
              )}
            </div>
          ))}
        </section>
      ) : null}
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
        <div className="ca-trail-actions">
          <label className="ca-trail-relevant">
            <input
              checked={entry.still_relevant}
              onChange={(event) => {
                const stillRelevant = event.currentTarget.checked;
                void attempt(() => onSetRelevant(entry.id, stillRelevant));
              }}
              type="checkbox"
            />
            Still relevant
          </label>
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
      )}
    </article>
  );
}

export function LearningTrail({
  entries,
  focusEntryId,
  onCreate,
  readOnly = false,
  ...entryActions
}: LearningTrailProps) {
  const [view, setView] = useState<"recent" | "all">(
    focusEntryId !== undefined && focusEntryId !== entries[0]?.id ? "all" : "recent",
  );
  const [composing, setComposing] = useState(false);
  const [openEntryId, setOpenEntryId] = useState<string | undefined>(focusEntryId);
  const latestIdRef = useRef(entries[0]?.id);
  latestIdRef.current = entries[0]?.id;

  useEffect(() => {
    // Follow the agent when it points at another entry; a later save must not move the reader.
    if (focusEntryId === undefined) return;
    setOpenEntryId(focusEntryId);
    setView(focusEntryId === latestIdRef.current ? "recent" : "all");
  }, [focusEntryId]);

  const latest = entries[0];

  return (
    <section aria-label="Learning trail" className="ca-learning-trail">
      <header className="ca-trail-header">
        <h2>Learning trail</h2>
        <p className="ca-trail-note">
          Only you can open these here. When you chat, the Course Agent reads the entries you keep
          as relevant, through the course&rsquo;s model provider, to connect your work across
          weeks. It cannot change them.
        </p>
        <div className="ca-trail-actions">
          {readOnly ? null : (
            <Button
              className="ca-trail-action"
              onClick={() => setComposing(true)}
              variant="outline"
            >
              New reflection
            </Button>
          )}
          {entries.length > 1 ? (
            <Button
              aria-pressed={view === "all"}
              className="ca-trail-action"
              onClick={() => setView(view === "all" ? "recent" : "all")}
            >
              {view === "all" ? "Show most recent" : `View all ${entries.length}`}
            </Button>
          ) : null}
        </div>
      </header>
      {composing ? (
        <EntryForm
          onCancel={() => setComposing(false)}
          onSubmit={async (draft) => {
            await onCreate(draft);
            setComposing(false);
            setView("recent");
          }}
        />
      ) : null}
      {latest === undefined ? (
        composing ? null : (
          <p className="ca-trail-note">
            Nothing saved yet. Write a reflection after each build, in your own words.
          </p>
        )
      ) : view === "recent" ? (
        <Entry entry={latest} key={latest.id} readOnly={readOnly} {...entryActions} />
      ) : (
        <ol className="ca-trail-timeline">
          {entries.map((entry) => (
            <li data-set-aside={!entry.still_relevant} key={entry.id}>
              <button
                aria-expanded={openEntryId === entry.id}
                className="ca-trail-row"
                onClick={() => setOpenEntryId(openEntryId === entry.id ? undefined : entry.id)}
                type="button"
              >
                <span className="ca-trail-kicker">Week {entry.week}</span>
                <span>{entry.build_title}</span>
                <span className="ca-trail-kicker">
                  {entry.still_relevant ? "" : "Set aside"}
                </span>
              </button>
              {openEntryId === entry.id ? (
                <Entry entry={entry} readOnly={readOnly} {...entryActions} />
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
