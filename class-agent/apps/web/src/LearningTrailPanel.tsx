import {
  LearningTrail,
  LearningTrailStaff,
  type LearningTrailEntry,
  type LearningTrailStudent,
} from "@class-agent/ui";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  addLearningTrailFeedback,
  addStaffLearningTrailFeedback,
  createLearningTrailEntry,
  deleteLearningTrailEntry,
  deleteLearningTrailFeedback,
  deleteStaffLearningTrailFeedback,
  listLearningTrail,
  listLearningTrailStudents,
  listSharedLearningTrail,
  updateLearningTrailEntry,
} from "./api.js";

interface LearningTrailPanelProps {
  focusEntryId?: string | undefined;
  readOnly: boolean;
}

const LOAD_ERROR = "The learning trail could not be loaded. Please try again.";

function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

function StudentView({
  entries: initialEntries,
  focusEntryId,
  readOnly,
}: LearningTrailPanelProps & { entries: LearningTrailEntry[] }) {
  const [entries, setEntries] = useState(initialEntries);
  const reload = async () => setEntries(await listLearningTrail());

  return (
    <LearningTrail
      entries={entries}
      focusEntryId={focusEntryId}
      onAddFeedback={async (entryId, draft) => {
        await addLearningTrailFeedback(entryId, draft);
        await reload();
      }}
      onCreate={async (draft) => {
        await createLearningTrailEntry(draft);
        await reload();
      }}
      onDelete={async (entryId) => {
        await deleteLearningTrailEntry(entryId);
        await reload();
      }}
      onDeleteFeedback={async (entryId, feedbackId) => {
        await deleteLearningTrailFeedback(entryId, feedbackId);
        await reload();
      }}
      onEdit={async (entryId, draft) => {
        await updateLearningTrailEntry(entryId, draft);
        await reload();
      }}
      onSetRelevant={async (entryId, stillRelevant) => {
        await updateLearningTrailEntry(entryId, { still_relevant: stillRelevant });
        await reload();
      }}
      onSetShared={async (entryId, shared) => {
        await updateLearningTrailEntry(entryId, { shared_with_staff: shared });
        await reload();
      }}
      readOnly={readOnly}
    />
  );
}

function StaffView({
  readOnly,
  students: initialStudents,
}: {
  readOnly: boolean;
  students: LearningTrailStudent[];
}) {
  const [students, setStudents] = useState(initialStudents);
  const [selected, setSelected] = useState<LearningTrailStudent | undefined>();
  const [entries, setEntries] = useState<LearningTrailEntry[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const select = useCallback(async (student: LearningTrailStudent | undefined) => {
    setMessage(null);
    try {
      if (student === undefined) {
        setStudents(await listLearningTrailStudents());
        setEntries([]);
      } else {
        setEntries(await listSharedLearningTrail(student.student_id));
      }
      setSelected(student);
    } catch {
      setMessage(LOAD_ERROR);
    }
  }, []);

  if (message) return <p className="workspace-panel-message">{message}</p>;

  return (
    <LearningTrailStaff
      entries={entries}
      onAddFeedback={async (entryId, body) => {
        if (selected === undefined) return;
        await addStaffLearningTrailFeedback(selected.student_id, entryId, body);
        setEntries(await listSharedLearningTrail(selected.student_id));
      }}
      onDeleteFeedback={async (entryId, feedbackId) => {
        if (selected === undefined) return;
        await deleteStaffLearningTrailFeedback(selected.student_id, entryId, feedbackId);
        setEntries(await listSharedLearningTrail(selected.student_id));
      }}
      onSelectStudent={(student) => void select(student)}
      readOnly={readOnly}
      selectedStudent={selected}
      students={students}
    />
  );
}

type Loaded =
  | { view: "student"; entries: LearningTrailEntry[] }
  | { view: "staff"; students: LearningTrailStudent[] };

async function loadTrail(): Promise<Loaded> {
  try {
    return { view: "student", entries: await listLearningTrail() };
  } catch (error) {
    if (!isForbidden(error)) throw error;
  }
  return { view: "staff", students: await listLearningTrailStudents() };
}

/** Trail data is fetched here, not carried in workspace props, so it stays out of chat history. */
export function LearningTrailPanel({ focusEntryId, readOnly }: LearningTrailPanelProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    loadTrail().then(
      (result) => {
        if (!disposed) setLoaded(result);
      },
      (error: unknown) => {
        if (disposed) return;
        setMessage(
          isForbidden(error) ? "Log in with a course account to use the learning trail." : LOAD_ERROR,
        );
      },
    );
    return () => {
      disposed = true;
    };
  }, []);

  if (message) return <p className="workspace-panel-message">{message}</p>;
  if (loaded === null) return <p className="workspace-panel-message">Opening the trail…</p>;
  if (loaded.view === "staff") {
    return <StaffView readOnly={readOnly} students={loaded.students} />;
  }
  return <StudentView entries={loaded.entries} focusEntryId={focusEntryId} readOnly={readOnly} />;
}
