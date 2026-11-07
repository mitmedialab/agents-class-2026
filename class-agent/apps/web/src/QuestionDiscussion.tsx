import { Button } from "@class-agent/ui";
import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  getQuestionDiscussion,
  sendQuestionReply,
  type QuestionDiscussion as QuestionDiscussionData,
} from "./api.js";

export function QuestionDiscussion({ questionId }: { questionId: string }) {
  const [discussion, setDiscussion] = useState<QuestionDiscussionData | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const requestVersion = useRef(0);
  const hasLoaded = useRef(false);

  useEffect(() => {
    let active = true;
    hasLoaded.current = false;
    setDiscussion(null);
    setError(null);
    function refresh() {
      const version = ++requestVersion.current;
      void getQuestionDiscussion(questionId)
        .then((result) => {
          if (active && version === requestVersion.current) {
            hasLoaded.current = true;
            setDiscussion(result);
            setError(null);
          }
        })
        .catch(() => {
          if (active && version === requestVersion.current) {
            setError(
              hasLoaded.current
                ? "Conversation could not be refreshed."
                : "Conversation could not be loaded.",
            );
          }
        });
    }
    refresh();
    const interval = window.setInterval(() => {
      if (!document.hidden) refresh();
    }, 30_000);
    window.addEventListener("focus", refresh);
    return () => {
      active = false;
      window.clearInterval(interval);
      window.removeEventListener("focus", refresh);
    };
  }, [questionId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.trim() || sending) return;
    setSending(true);
    setError(null);
    ++requestVersion.current;
    try {
      const updated = await sendQuestionReply(questionId, draft);
      setDiscussion(updated);
      setDraft("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Reply could not be sent.");
    } finally {
      setSending(false);
    }
  }

  if (!discussion) {
    return <p className="question-discussion-status" role={error ? "alert" : "status"}>
      {error ?? "Loading conversation..."}
    </p>;
  }

  return (
    <div className="question-discussion">
      <h3>{discussion.subject}</h3>
      <ol className="question-discussion-messages">
        <li>
          <span>{discussion.viewer_role === "student" ? "You" : discussion.student_label}</span>
          <p>{discussion.question}</p>
        </li>
        {discussion.answer ? <li>
          <span>Course staff</span>
          <p>{discussion.answer}</p>
        </li> : null}
        {discussion.replies.map((reply) => <li key={reply.id}>
          <span>{reply.sender_label}</span>
          <p>{reply.body}</p>
        </li>)}
      </ol>
      {discussion.can_reply ? <form className="question-discussion-form" onSubmit={submit}>
        <label htmlFor={`question-reply-${questionId}`}>Reply to {discussion.viewer_role === "student" ? "course staff" : "student"}</label>
        <textarea
          id={`question-reply-${questionId}`}
          maxLength={10_000}
          onChange={(event) => setDraft(event.target.value)}
          rows={3}
          value={draft}
        />
        <Button disabled={!draft.trim() || sending} type="submit">
          {sending ? "Sending..." : "Send reply"}
        </Button>
      </form> : null}
      {error ? <p className="question-discussion-error" role="alert">{error}</p> : null}
    </div>
  );
}
