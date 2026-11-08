import type { Memory, Uuid } from "@class-agent/protocol";
import { Button } from "@class-agent/ui";
import { useEffect, useState } from "react";
import { deleteMemory, listMemories, updateMemory } from "./api.js";

const MEMORY_MAX_LENGTH = 2000;

export function MemoriesPage({ onBack }: { onBack: () => void }) {
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [editing, setEditing] = useState<{ id: Uuid; draft: string } | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState<Uuid | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listMemories()
      .then((loaded) => {
        if (active) setMemories(loaded);
      })
      .catch(() => {
        if (active) setError("Your memories could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, []);

  async function run(action: () => Promise<void>, failure: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  const save = (id: Uuid, draft: string) =>
    run(async () => {
      const updated = await updateMemory(id, draft.trim());
      // An edit makes the memory the most recent, matching the server's order.
      setMemories((current) => [updated, ...(current ?? []).filter((m) => m.id !== id)]);
      setEditing(null);
    }, "That memory could not be saved.");

  const remove = (id: Uuid) =>
    run(async () => {
      await deleteMemory(id);
      setMemories((current) => (current ?? []).filter((m) => m.id !== id));
      setConfirmingDelete(null);
    }, "That memory could not be deleted.");

  return (
    <main className="syllabus-page">
      <div className="syllabus-document">
        <h1>Your memories</h1>
        <div className="syllabus-sections">
          <p>
            The newest 20 are given to the Course Agent in your conversations. Editing or
            deleting one here does not change earlier conversations.
          </p>
          {error ? <p role="alert">{error}</p> : null}
          {memories === null && !error ? <p>Loading.</p> : null}
          {memories?.length === 0 ? <p>The agent has not saved any memories yet.</p> : null}
          {memories && memories.length > 0 ? (
            <ul className="memory-list">
              {memories.map((memory) => (
                <li key={memory.id}>
                  <p className="memory-kind">{memory.kind}</p>
                  {editing?.id === memory.id ? (
                    <>
                      <textarea
                        aria-label="Edit memory"
                        className="ca-input"
                        maxLength={MEMORY_MAX_LENGTH}
                        onChange={(event) =>
                          setEditing({ id: memory.id, draft: event.target.value })
                        }
                        rows={3}
                        value={editing.draft}
                      />
                      <div className="memory-actions">
                        <Button
                          disabled={busy || !editing.draft.trim()}
                          onClick={() => void save(memory.id, editing.draft)}
                          variant="outline"
                        >
                          Save
                        </Button>
                        <Button disabled={busy} onClick={() => setEditing(null)}>
                          Cancel
                        </Button>
                      </div>
                    </>
                  ) : (
                    <>
                      <p>{memory.content}</p>
                      <div className="memory-actions">
                        {confirmingDelete === memory.id ? (
                          <>
                            <Button
                              disabled={busy}
                              onClick={() => void remove(memory.id)}
                              variant="outline"
                            >
                              Confirm delete
                            </Button>
                            <Button disabled={busy} onClick={() => setConfirmingDelete(null)}>
                              Keep
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button
                              aria-label={`Edit: ${memory.content}`}
                              disabled={busy}
                              onClick={() => {
                                setConfirmingDelete(null);
                                setEditing({ id: memory.id, draft: memory.content });
                              }}
                            >
                              Edit
                            </Button>
                            <Button
                              aria-label={`Delete: ${memory.content}`}
                              disabled={busy}
                              onClick={() => {
                                setEditing(null);
                                setConfirmingDelete(memory.id);
                              }}
                            >
                              Delete
                            </Button>
                          </>
                        )}
                      </div>
                    </>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
          <div className="onboarding-actions">
            <Button onClick={onBack}>Back to conversation</Button>
          </div>
        </div>
      </div>
    </main>
  );
}
