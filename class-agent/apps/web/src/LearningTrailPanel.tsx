import { LearningTrail, type LearningTrailEntry } from "@class-agent/ui";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  addLearningTrailFeedback,
  createLearningTrailEntry,
  deleteLearningTrailEntry,
  deleteLearningTrailFeedback,
  listLearningTrail,
  updateLearningTrailEntry,
} from "./api.js";

interface LearningTrailPanelProps {
  focusEntryId?: string | undefined;
  readOnly: boolean;
}

/** Trail data is fetched here, not carried in workspace props, so it stays out of chat history. */
export function LearningTrailPanel({ focusEntryId, readOnly }: LearningTrailPanelProps) {
  const [entries, setEntries] = useState<LearningTrailEntry[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setEntries(await listLearningTrail());
  }, []);

  useEffect(() => {
    let disposed = false;
    listLearningTrail().then(
      (loaded) => {
        if (!disposed) setEntries(loaded);
      },
      (error: unknown) => {
        if (disposed) return;
        setMessage(
          error instanceof ApiError && error.status === 403
            ? "Log in with a student account to use the learning trail."
            : "The learning trail could not be loaded. Please try again.",
        );
      },
    );
    return () => {
      disposed = true;
    };
  }, []);

  if (message) return <p className="workspace-panel-message">{message}</p>;
  if (entries === null) return <p className="workspace-panel-message">Opening your trail…</p>;

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
      readOnly={readOnly}
    />
  );
}
