import { useEffect, useId, useState, type FormEvent } from "react";

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
  still_relevant: boolean;
  shared_with_staff: boolean;
  feedback: LearningTrailFeedback[];
  created_at: string;
  updated_at: string;
}

export interface LearningTrailEntryDraft {
  week: number;
  build_title: string;
  build_url: string | null;
  reflection: string;
  shared_with_staff: boolean;
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
  focusEntryId?: string | undefined;
  /** History views show what is saved now and do not allow changes. */
  readOnly?: boolean;
  onCreate: (draft: LearningTrailEntryDraft) => Promise<void>;
  onEdit: (entryId: string, draft: LearningTrailEntryDraft) => Promise<void>;
  onSetRelevant: (entryId: string, stillRelevant: boolean) => Promise<void>;
  onSetShared: (entryId: string, shared: boolean) => Promise<void>;
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

const HOW_IT_WORKS = [
  { title: "Save", text: "After each build, write down what you made and what you learned." },
  { title: "Get feedback", text: "Let TAs see a build if you want them to comment on it." },
  { title: "Ask", text: "Ask the agent for help. It uses your notes and says which week it used." },
] as const;

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
  entry,
  initialWeek,
  onCancel,
  onSubmit,
}: {
  entry?: LearningTrailEntry | undefined;
  initialWeek?: number | undefined;
  onCancel: () => void;
  onSubmit: (draft: LearningTrailEntryDraft) => Promise<void>;
}) {
  const [week, setWeek] = useState(String(entry?.week ?? initialWeek ?? ""));
  const [title, setTitle] = useState(entry?.build_title ?? "");
  const [url, setUrl] = useState(entry?.build_url ?? "");
  const [reflection, setReflection] = useState(entry?.reflection ?? "");
  const [shared, setShared] = useState(entry?.shared_with_staff ?? true);
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
        shared_with_staff: shared,
      });
    } catch {
      setError(SAVE_ERROR);
      setSaving(false);
    }
  };

  return (
    <form
      aria-label={entry ? "Edit build" : "Add a build"}
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
      <label className="ca-trail-relevant">
        <input
          checked={shared}
          onChange={(event) => setShared(event.currentTarget.checked)}
          type="checkbox"
        />
        TAs can see this
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
  onDelete,
  onDeleteFeedback,
  onEdit,
  onSetRelevant,
  onSetShared,
  readOnly,
}: {
  entry: LearningTrailEntry;
  readOnly: boolean;
} & Pick<
  LearningTrailProps,
  | "onAddFeedback"
  | "onAsk"
  | "onDelete"
  | "onDeleteFeedback"
  | "onEdit"
  | "onSetRelevant"
  | "onSetShared"
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
    <div className="ca-trail-entry">
      <p className="ca-trail-text">{entry.reflection}</p>
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
            <label className="ca-trail-toggle">
              <input
                checked={entry.still_relevant}
                onChange={(event) => {
                  const stillRelevant = event.currentTarget.checked;
                  void attempt(() => onSetRelevant(entry.id, stillRelevant));
                }}
                type="checkbox"
              />
              <span>
                The agent can use this
                <small>Turn off to keep the note here without it affecting the agent&rsquo;s help.</small>
              </span>
            </label>
            <label className="ca-trail-toggle">
              <input
                checked={entry.shared_with_staff}
                onChange={(event) => {
                  const shared = event.currentTarget.checked;
                  void attempt(() => onSetShared(entry.id, shared));
                }}
                type="checkbox"
              />
              <span>
                TAs can see this
                <small>Turn on if you want a TA or instructor to read it and comment.</small>
              </span>
            </label>
          </div>
          <div className="ca-trail-actions">
            {onAsk ? (
              <Button className="ca-trail-action" onClick={() => onAsk(weekQuestion(entry))}>
                Ask about this week
              </Button>
            ) : null}
            <Button className="ca-trail-action" onClick={() => setMode("feedback")}>
              Add feedback you received
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
    </div>
  );
}

function entryStatus(entry: LearningTrailEntry): string {
  const feedback = entry.feedback.length;
  return [
    entry.still_relevant ? "Agent uses this" : "Agent does not use this",
    entry.shared_with_staff ? "TAs can see" : "Only you",
    ...(feedback > 0 ? [`${feedback} feedback`] : []),
  ].join(" · ");
}

export function LearningTrail({
  entries,
  focusEntryId,
  onAsk,
  onCreate,
  readOnly = false,
  ...entryActions
}: LearningTrailProps) {
  const [composingWeek, setComposingWeek] = useState<number | null>(null);
  const [openEntryId, setOpenEntryId] = useState<string | undefined>(focusEntryId);

  useEffect(() => {
    // Follow the agent when it points at another entry; a later save must not move the reader.
    if (focusEntryId !== undefined) setOpenEntryId(focusEntryId);
  }, [focusEntryId]);

  const latestWeek = entries.reduce((latest, entry) => Math.max(latest, entry.week), 0);
  const savedWeeks = new Set(entries.map((entry) => entry.week));
  const missingWeeks = Array.from({ length: latestWeek }, (_, index) => index + 1).filter(
    (week) => !savedWeeks.has(week),
  );
  const rows = [
    ...entries.map((entry) => ({ week: entry.week, entry })),
    ...missingWeeks.map((week) => ({ week, entry: undefined })),
  ].sort((a, b) => b.week - a.week);

  return (
    <section aria-label="Learning trail" className="ca-learning-trail">
      <header className="ca-trail-header">
        <p className="ca-trail-kicker">Learning trail</p>
        <h2>My builds</h2>
        <p className="ca-trail-note">
          Your notes on each weekly build. The Course Agent reads them when it helps you, so its
          help can build on what you have already done. Only you can change them.
        </p>
      </header>
      {readOnly ? null : (
        <ol aria-label="How it works" className="ca-trail-steps">
          {HOW_IT_WORKS.map((step, index) => (
            <li key={step.title}>
              <span className="ca-trail-kicker">{index + 1}</span>
              <strong>{step.title}</strong>
              <span>{step.text}</span>
            </li>
          ))}
        </ol>
      )}
      {readOnly ? null : (
        <div className="ca-trail-actions">
          <Button
            className="ca-trail-action"
            onClick={() => setComposingWeek(latestWeek + 1)}
            variant={entries.length === 0 ? "outline" : "plain"}
          >
            Add a build
          </Button>
          {onAsk && entries.length > 0 ? (
            <Button
              className="ca-trail-action"
              onClick={() => onAsk(NEXT_BUILD_QUESTION)}
              variant="outline"
            >
              Ask the agent about my next build
            </Button>
          ) : null}
        </div>
      )}
      {composingWeek !== null ? (
        <EntryForm
          initialWeek={composingWeek}
          key={composingWeek}
          onCancel={() => setComposingWeek(null)}
          onSubmit={async (draft) => {
            await onCreate(draft);
            setComposingWeek(null);
          }}
        />
      ) : null}
      {rows.length > 0 ? (
        <ol className="ca-trail-weeks">
          {rows.map(({ week, entry }) =>
            entry === undefined ? (
              <li data-state="empty" key={`week-${week}`}>
                <div className="ca-trail-row ca-trail-row--empty">
                  <span className="ca-trail-kicker">Week {week}</span>
                  <span className="ca-trail-row-body">
                    <span>Nothing saved</span>
                    {readOnly ? null : (
                      <Button
                        aria-label={`Add a build for Week ${week}`}
                        className="ca-trail-action"
                        onClick={() => setComposingWeek(week)}
                      >
                        Add
                      </Button>
                    )}
                  </span>
                </div>
              </li>
            ) : (
              <li data-state={entry.still_relevant ? "used" : "unused"} key={entry.id}>
                <button
                  aria-expanded={openEntryId === entry.id}
                  className="ca-trail-row"
                  onClick={() => setOpenEntryId(openEntryId === entry.id ? undefined : entry.id)}
                  type="button"
                >
                  <span className="ca-trail-kicker">Week {entry.week}</span>
                  <span className="ca-trail-row-body">
                    <span className="ca-trail-row-title">{entry.build_title}</span>
                    {openEntryId === entry.id ? null : (
                      <span className="ca-trail-excerpt">{entry.reflection}</span>
                    )}
                    <span className="ca-trail-status">{entryStatus(entry)}</span>
                  </span>
                </button>
                {openEntryId === entry.id ? (
                  <EntryDetails
                    entry={entry}
                    onAsk={onAsk}
                    readOnly={readOnly}
                    {...entryActions}
                  />
                ) : null}
              </li>
            ),
          )}
        </ol>
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
