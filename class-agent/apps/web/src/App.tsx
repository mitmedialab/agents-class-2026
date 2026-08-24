import type { Conversation, Event, PrincipalContext } from "@class-agent/protocol";
import { Button, TextInput } from "@class-agent/ui";
import {
  createConversation,
  getConversation,
  getPrincipal,
  listConversations,
  login,
  logout,
  streamAgentRun,
  type AgentActivity,
  type AgentStreamEvent,
} from "./api.js";
import { ActivityTrace } from "./ActivityTrace.js";
import { AgentResponse } from "./AgentResponse.js";
import { TextRevealQueue } from "./textReveal.js";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";

const CONNECTION_ERROR = "I couldn’t reach the Course Agent. Please try again.";
const WELCOME_MESSAGE =
  "Welcome. I’m the Course Agent. This agent is the class website—ask me for class information, or talk with me if you’d like to apply.";

function newestFirst(conversations: Conversation[]): Conversation[] {
  return [...conversations].sort(
    (left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at),
  );
}

function latestAgentResponse(events: Event[]): string {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event?.type === "agent.message" && typeof event.payload.text === "string") {
      return event.payload.text;
    }
  }
  return "";
}

function conversationTitle(conversation: Conversation): string {
  return conversation.title?.trim() || "Untitled conversation";
}

function titleFromMessage(message: string): string {
  const singleLine = message.replaceAll(/\s+/g, " ").trim();
  return singleLine.length > 56 ? `${singleLine.slice(0, 55)}…` : singleLine;
}

function formatConversationDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

export default function App() {
  const [principal, setPrincipal] = useState<PrincipalContext | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [latestResponse, setLatestResponse] = useState(WELCOME_MESSAGE);
  const [currentAction, setCurrentAction] = useState<string | null>("Connecting");
  const [activities, setActivities] = useState<AgentActivity[]>([]);
  const [message, setMessage] = useState("");
  const [isInitializing, setIsInitializing] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [isStreamingText, setIsStreamingText] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [accessCode, setAccessCode] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const activeRun = useRef<AbortController | null>(null);
  const activeReveal = useRef<TextRevealQueue | null>(null);

  async function showConversation(conversation: Conversation): Promise<void> {
    setCurrentAction("Loading conversation");
    try {
      const detail = await getConversation(conversation.id);
      setSelectedConversationId(conversation.id);
      setLatestResponse(latestAgentResponse(detail.events) || WELCOME_MESSAGE);
      setActivities([]);
      setDrawerOpen(false);
    } catch {
      setLatestResponse(CONNECTION_ERROR);
    } finally {
      setCurrentAction(null);
    }
  }

  async function loadConversationList(): Promise<Conversation[]> {
    const loaded = newestFirst(await listConversations());
    setConversations(loaded);
    return loaded;
  }

  useEffect(() => {
    let disposed = false;

    async function initialize() {
      try {
        const resolvedPrincipal = await getPrincipal();
        if (disposed) return;
        setPrincipal(resolvedPrincipal);
        const loaded = await listConversations();
        if (disposed) return;
        const sorted = newestFirst(loaded);
        setConversations(sorted);
        const newest = sorted[0];
        if (newest) {
          const detail = await getConversation(newest.id);
          if (disposed) return;
          setSelectedConversationId(newest.id);
          setLatestResponse(latestAgentResponse(detail.events) || WELCOME_MESSAGE);
        }
      } catch {
        if (!disposed) setLatestResponse(CONNECTION_ERROR);
      } finally {
        if (!disposed) {
          setCurrentAction(null);
          setIsInitializing(false);
        }
      }
    }

    void initialize();
    return () => {
      disposed = true;
      activeRun.current?.abort();
      activeReveal.current?.cancel();
    };
  }, []);

  useEffect(() => {
    const composer = composerRef.current;
    if (!composer) return;
    composer.style.height = "0px";
    composer.style.height = `${Math.min(composer.scrollHeight, 160)}px`;
  }, [message]);

  useEffect(() => {
    function focusComposer(event: globalThis.KeyboardEvent) {
      const target = event.target;
      if (
        drawerOpen ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        event.key.length !== 1 ||
        (target instanceof HTMLElement && target.isContentEditable) ||
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement
      ) {
        return;
      }
      composerRef.current?.focus();
    }

    window.addEventListener("keydown", focusComposer);
    return () => window.removeEventListener("keydown", focusComposer);
  }, [drawerOpen]);

  useEffect(() => {
    if (!drawerOpen) return;

    const previouslyFocused = document.activeElement;
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const frame = requestAnimationFrame(() => {
      drawerRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    });

    function handleDrawerKeys(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setDrawerOpen(false);
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;

      const focusable = Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        ),
      );
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleDrawerKeys);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleDrawerKeys);
      document.body.style.overflow = priorOverflow;
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  }, [drawerOpen]);

  async function sendMessage(): Promise<void> {
    const text = message.trim();
    if (!text || isInitializing || isRunning) return;

    setMessage("");
    setIsRunning(true);
    setIsStreamingText(false);
    setCurrentAction("Preparing conversation context");
    setActivities([]);
    setLatestResponse("");
    let conversationId = selectedConversationId;
    let receivedError = false;
    let writingActivityRecorded = false;
    let progressText = "";
    let presentationFinished: Promise<void> | null = null;
    const controller = new AbortController();
    activeRun.current = controller;
    activeReveal.current?.cancel();
    const reveal = new TextRevealQueue((visibleText, active) => {
      setLatestResponse(visibleText);
      setIsStreamingText(active);
    });
    activeReveal.current = reveal;

    try {
      if (!conversationId) {
        const created = await createConversation(titleFromMessage(text));
        conversationId = created.id;
        setSelectedConversationId(created.id);
        setConversations((current) => newestFirst([created, ...current]));
      }

      const handleStreamEvent = (event: AgentStreamEvent) => {
        if (event.kind === "text") {
          setIsStreamingText(true);
          setCurrentAction("Writing final response");
          if (!writingActivityRecorded) {
            writingActivityRecorded = true;
            setActivities((current) => [
              ...current,
              { kind: "output", label: "Writing final response" },
            ]);
          }
          reveal.append(event.text);
        } else if (event.kind === "text_final") {
          presentationFinished = reveal.finish(event.text);
        } else if (event.kind === "progress") {
          progressText += event.text;
          const progressResponse = progressText.trim();
          if (!progressResponse) return;
          setLatestResponse(progressResponse);
          setIsStreamingText(true);
          setCurrentAction("Sharing intermediate update");
          setActivities((current) => {
            const progressActivity: AgentActivity = {
              id: "model-progress",
              kind: "output",
              label: "Shared intermediate update",
            };
            const existingIndex = current.findIndex(
              (activity) => activity.id === progressActivity.id,
            );
            if (existingIndex < 0) return [...current, progressActivity];
            const next = [...current];
            next[existingIndex] = progressActivity;
            return next;
          });
        } else if (event.kind === "activity") {
          setActivities((current) => [...current, event.activity]);
          setCurrentAction(event.activity.label);
        } else if (event.kind === "done") {
          setActivities((current) => [
            ...current,
            { kind: "complete", label: "Agent run complete" },
          ]);
        } else if (event.kind === "error") {
          receivedError = true;
          reveal.cancel();
          setLatestResponse(CONNECTION_ERROR);
          setActivities((current) => [
            ...current,
            { kind: "error", label: "Agent run failed" },
          ]);
        }
      };

      await streamAgentRun(conversationId, text, handleStreamEvent, controller.signal);
      if (!receivedError) {
        presentationFinished ??= reveal.finish();
        setCurrentAction("Presenting response");
        await presentationFinished;
      }
      try {
        await loadConversationList();
      } catch {
        // The completed answer remains usable if refreshing navigation fails.
      }
    } catch (error) {
      reveal.cancel();
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setLatestResponse(CONNECTION_ERROR);
      }
    } finally {
      activeRun.current = null;
      if (activeReveal.current === reveal) activeReveal.current = null;
      setCurrentAction(null);
      setIsStreamingText(false);
      setIsRunning(false);
      requestAnimationFrame(() => composerRef.current?.focus());
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  function startNewConversation() {
    setSelectedConversationId(null);
    setLatestResponse(WELCOME_MESSAGE);
    setActivities([]);
    setCurrentAction(null);
    setDrawerOpen(false);
    requestAnimationFrame(() => composerRef.current?.focus());
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthSubmitting(true);
    setAuthError(null);
    try {
      const nextPrincipal = await login(username.trim(), accessCode);
      setPrincipal(nextPrincipal);
      setAccessCode("");
      const loaded = await loadConversationList();
      const newest = loaded[0];
      if (newest) {
        await showConversation(newest);
      } else {
        startNewConversation();
      }
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Login failed");
    } finally {
      setAuthSubmitting(false);
    }
  }

  async function handleLogout() {
    setAuthSubmitting(true);
    setAuthError(null);
    try {
      await logout();
      const nextPrincipal = await getPrincipal();
      setPrincipal(nextPrincipal);
      const loaded = await loadConversationList();
      const newest = loaded[0];
      if (newest) {
        await showConversation(newest);
      } else {
        startNewConversation();
      }
    } catch {
      setAuthError("Logout failed");
    } finally {
      setAuthSubmitting(false);
    }
  }

  return (
    <div className="course-agent">
      <header className="agent-header">
        <div aria-label="MIT and MIT Media Lab" className="institutional-marks">
          <a aria-label="MIT" href="https://www.mit.edu/">
            <img alt="" className="mit-mark" src="/mit-logo.svg" />
          </a>
          <a aria-label="MIT Media Lab" href="https://www.media.mit.edu/">
            <img alt="" className="media-lab-mark" src="/media-lab-logo.svg" />
          </a>
        </div>
        <Button
          aria-expanded={drawerOpen}
          aria-haspopup="dialog"
          className="about-link"
          onClick={() => setDrawerOpen(true)}
        >
          About
        </Button>
      </header>

      <main className="workspace-shell" data-testid="workspace-shell">
        <section aria-atomic="false" aria-live="polite" className="response-stage">
          <div className="response-agent-line" data-testid="response-agent-line">
            <span className="response-agent-name">Course Agent</span>
            <ActivityTrace activities={activities} currentLabel={currentAction} />
          </div>
          {latestResponse ? (
            <AgentResponse streaming={isStreamingText} text={latestResponse} />
          ) : null}
        </section>
      </main>

      <form
        aria-label="Message Course Agent"
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          void sendMessage();
        }}
      >
        <textarea
          ref={composerRef}
          aria-label="Message"
          autoComplete="off"
          autoFocus
          className="composer-text"
          disabled={isInitializing || isRunning}
          enterKeyHint="send"
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={handleComposerKeyDown}
          placeholder="Start typing to interact with the agent"
          rows={1}
          spellCheck
          value={message}
        />
        <button aria-hidden="true" className="visually-hidden" tabIndex={-1} type="submit">
          Send
        </button>
      </form>

      {drawerOpen ? (
        <div
          className="drawer-backdrop"
          onClick={() => setDrawerOpen(false)}
          role="presentation"
        >
          <aside
            ref={drawerRef}
            aria-label="About Course Agent"
            aria-modal="true"
            className="agent-drawer"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
          >
            <div className="drawer-heading">
              <span>About</span>
              <Button aria-label="Close menu" onClick={() => setDrawerOpen(false)}>
                Close
              </Button>
            </div>

            <div className="drawer-about-copy">
              <p>The Course Agent is the class website.</p>
              <p>
                Ask it for course information, discuss applying, or start a new
                conversation at any time.
              </p>
            </div>

            <Button className="new-conversation" onClick={startNewConversation} variant="outline">
              New conversation
            </Button>

            <nav aria-label="Conversations" className="conversation-navigation">
              <p className="drawer-label">Conversations</p>
              {conversations.length === 0 ? (
                <p className="empty-list">No conversations yet.</p>
              ) : (
                <ol className="conversation-list">
                  {conversations.map((conversation) => (
                    <li key={conversation.id}>
                      <Button
                        aria-current={
                          selectedConversationId === conversation.id ? "page" : undefined
                        }
                        className="conversation-link"
                        onClick={() => void showConversation(conversation)}
                      >
                        <span>{conversationTitle(conversation)}</span>
                        <time dateTime={conversation.updated_at}>
                          {formatConversationDate(conversation.updated_at)}
                        </time>
                      </Button>
                    </li>
                  ))}
                </ol>
              )}
            </nav>

            <section className="account-section">
              {principal?.authenticated ? (
                <>
                  <p className="drawer-label">Signed in</p>
                  <p className="account-name">
                    {principal.display_name || principal.username || "Course member"}
                  </p>
                  <Button disabled={authSubmitting} onClick={() => void handleLogout()}>
                    Log out
                  </Button>
                </>
              ) : (
                <form className="login-form" onSubmit={(event) => void handleLogin(event)}>
                  <p className="drawer-label">Student login</p>
                  <TextInput
                    autoComplete="username"
                    label="Username"
                    onChange={(event) => setUsername(event.target.value)}
                    required
                    value={username}
                  />
                  <TextInput
                    autoComplete="current-password"
                    label="Access code"
                    onChange={(event) => setAccessCode(event.target.value)}
                    required
                    type="password"
                    value={accessCode}
                  />
                  {authError ? <p className="auth-error">{authError}</p> : null}
                  <Button disabled={authSubmitting} type="submit" variant="outline">
                    {authSubmitting ? "Signing in" : "Log in"}
                  </Button>
                </form>
              )}
              {principal?.authenticated && authError ? (
                <p className="auth-error">{authError}</p>
              ) : null}
            </section>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
