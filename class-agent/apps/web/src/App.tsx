import type { Conversation, Event, PrincipalContext } from "@class-agent/protocol";
import { Button, TextInput } from "@class-agent/ui";
import {
  builtInComponentRegistry,
  emptyWorkspaceState,
  projectWorkspaceEvents,
  type JsonValue,
  type WorkspaceState,
} from "@class-agent/workspace";
import {
  applyWorkspacePanelAction,
  clickBrowserSession,
  confirmTAQuestion,
  continueAgentAfterEvent,
  createConversation,
  ensureApplicationDraft,
  getCourseResourceContent,
  getConversation,
  getPrincipal,
  listConversations,
  listNotifications,
  login,
  logout,
  markNotificationRead,
  recordWorkspaceInteraction,
  resizeBrowserSession,
  scrollBrowserSession,
  streamAgentRun,
  uploadFile,
  type AgentActivity,
  type AgentStreamEvent,
  type CourseNotification,
  type TemporaryUpload,
} from "./api.js";
import { ActivityTrace } from "./ActivityTrace.js";
import { CourseNotifications } from "./CourseNotifications.js";
import {
  AgentResponse,
  RESPONSE_CHARACTER_STAGGER_MS,
} from "./AgentResponse.js";
import { MorphingLineFigure } from "./MorphingLineFigure.js";
import { SyllabusPage } from "./SyllabusPage.js";
import { TAQuestionConfirmation } from "./TAQuestionConfirmation.js";
import { Workspace } from "./Workspace.js";
import {
  applyTAQuestionEvent,
  pendingTAQuestionContinuation,
  projectTAQuestionEvents,
  type TAQuestionConfirmation as TAQuestionConfirmationState,
} from "./taQuestions.js";
import {
  type DragEvent,
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

const CONNECTION_ERROR = "I couldn’t reach the Course Agent. Please try again.";
const WELCOME_MESSAGE =
  "Welcome. I’m the Course Agent. This agent is the class website—ask me for class information, or talk with me if you’d like to apply.";
const COURSE_TITLE = "MAS.S60 · AI Agents for Cognitive Augmentation";
const OPENING_SPLASH_DURATION_MS = 3_600;
const WELCOME_MORPH_DELAY_MS = 3_000;
const WELCOME_PRESENTATION_MS =
  WELCOME_MORPH_DELAY_MS +
  (WELCOME_MESSAGE.length - 1) * RESPONSE_CHARACTER_STAGGER_MS +
  180;
const INACTIVITY_TIMEOUT_MS = 5 * 60 * 1000;
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const SUPPORTED_UPLOAD_EXTENSIONS = new Set([
  "csv",
  "gif",
  "jpeg",
  "jpg",
  "json",
  "md",
  "pdf",
  "png",
  "txt",
  "webp",
]);
const SUPPORTED_UPLOAD_MEDIA_TYPES = new Set([
  "application/json",
  "application/pdf",
  "image/gif",
  "image/jpeg",
  "image/png",
  "image/webp",
  "text/csv",
  "text/markdown",
  "text/plain",
]);
const HEADER_PROMPTS = [
  { label: "Apply", message: "I'd like to apply for the course." },
  { label: "Schedule", message: "Show me the course schedule." },
  { label: "Grading", message: "How is grading handled in this course?" },
] as const;

function newestFirst(conversations: Conversation[]): Conversation[] {
  return [...conversations].sort(
    (left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at),
  );
}

function latestAgentResponse(events: Event[]): string {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (
      event?.type === "email.ta_answer.received" &&
      typeof event.payload.answer === "string"
    ) {
      return `Course staff replied:\n\n${event.payload.answer}`;
    }
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

function CloseIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="9.25" />
      <path d="m9 9 6 6m0-6-6 6" />
    </svg>
  );
}

function messageWithUploads(message: string, uploads: TemporaryUpload[]): string {
  if (uploads.length === 0) return message;
  const uploadContext = uploads
    .map(
      (upload) =>
        `[Temporary upload: ${upload.filename}; upload_id: ${upload.id}; ` +
        `media_type: ${upload.media_type}; expires_at: ${upload.expires_at}]`,
    )
    .join("\n");
  return `${message || "I attached file(s) for this conversation."}\n\n${uploadContext}`;
}

function uploadValidationError(files: File[]): string | null {
  const oversized = files.find((file) => file.size > MAX_UPLOAD_BYTES);
  if (oversized) return `“${oversized.name}” exceeds the 10 MB upload limit.`;

  const unsupported = files.find((file) => {
    const extension = file.name.split(".").at(-1)?.toLowerCase() ?? "";
    const mediaType = file.type.toLowerCase();
    return (
      !SUPPORTED_UPLOAD_EXTENSIONS.has(extension) &&
      !SUPPORTED_UPLOAD_MEDIA_TYPES.has(mediaType)
    );
  });
  return unsupported
    ? `“${unsupported.name}” isn’t supported. Upload an image, PDF, text, CSV, JSON, or Markdown file.`
    : null;
}

function formatConversationDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

function workspaceFromEvents(events: Event[]): WorkspaceState {
  try {
    return projectWorkspaceEvents(events);
  } catch {
    return emptyWorkspaceState();
  }
}

async function notificationsFor(
  resolvedPrincipal: PrincipalContext,
): Promise<CourseNotification[]> {
  if (
    !resolvedPrincipal.authenticated ||
    !resolvedPrincipal.roles.includes("student")
  ) {
    return [];
  }
  try {
    return await listNotifications();
  } catch {
    return [];
  }
}

export default function App() {
  const [principal, setPrincipal] = useState<PrincipalContext | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [latestResponse, setLatestResponse] = useState(WELCOME_MESSAGE);
  const [currentAction, setCurrentAction] = useState<string | null>("Connecting");
  const [activities, setActivities] = useState<AgentActivity[]>([]);
  const [workspaceState, setWorkspaceState] = useState<WorkspaceState>(
    emptyWorkspaceState,
  );
  const [message, setMessage] = useState("");
  const [isInitializing, setIsInitializing] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [isStreamingText, setIsStreamingText] = useState(false);
  const [isOpening, setIsOpening] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? !window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : true,
  );
  const [isPresentingWelcome, setIsPresentingWelcome] = useState(true);
  const [welcomePresentationId, setWelcomePresentationId] = useState(0);
  const [uploads, setUploads] = useState<TemporaryUpload[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isFileDragActive, setIsFileDragActive] = useState(false);
  const [pendingUploadCount, setPendingUploadCount] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [syllabusContent, setSyllabusContent] = useState<string | null>(null);
  const [syllabusError, setSyllabusError] = useState<string | null>(null);
  const [syllabusLoading, setSyllabusLoading] = useState(false);
  const [username, setUsername] = useState("");
  const [accessCode, setAccessCode] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [taQuestion, setTAQuestion] = useState<TAQuestionConfirmationState | null>(null);
  const [notifications, setNotifications] = useState<CourseNotification[]>([]);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const historyRef = useRef<HTMLElement>(null);
  const activeRun = useRef<AbortController | null>(null);
  const operationInFlight = useRef(false);
  const applicationReturnResponse = useRef<string | null>(null);
  const awaitingTAQuestionAction =
    taQuestion?.status === "pending_confirmation" ||
    taQuestion?.status === "submitting" ||
    taQuestion?.status === "error";

  const showWelcomeMessage = useCallback(() => {
    setLatestResponse(WELCOME_MESSAGE);
    setIsPresentingWelcome(true);
    setWelcomePresentationId((current) => current + 1);
  }, []);

  const startNewConversation = useCallback(() => {
    activeRun.current?.abort();
    activeRun.current = null;
    operationInFlight.current = false;
    applicationReturnResponse.current = null;
    setSelectedConversationId(null);
    showWelcomeMessage();
    setActivities([]);
    setWorkspaceState(emptyWorkspaceState());
    setCurrentAction(null);
    setMessage("");
    setUploads([]);
    setUploadError(null);
    setTAQuestion(null);
    setIsRunning(false);
    setIsStreamingText(false);
    setHistoryOpen(false);
    setAboutOpen(false);
    requestAnimationFrame(() => composerRef.current?.focus());
  }, [showWelcomeMessage]);

  async function showConversation(conversation: Conversation): Promise<void> {
    setCurrentAction("Loading conversation");
    try {
      const detail = await getConversation(conversation.id);
      setSelectedConversationId(conversation.id);
      const response = latestAgentResponse(detail.events);
      if (response) setLatestResponse(response);
      else showWelcomeMessage();
      setWorkspaceState(workspaceFromEvents(detail.events));
      setTAQuestion(projectTAQuestionEvents(detail.events));
      setActivities([]);
      setHistoryOpen(false);
      setAboutOpen(false);
      const pendingContinuation = pendingTAQuestionContinuation(detail.events);
      if (pendingContinuation) {
        await runAgentContinuation(conversation.id, pendingContinuation.id);
      }
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
        const [loaded, loadedNotifications] = await Promise.all([
          listConversations(),
          notificationsFor(resolvedPrincipal),
        ]);
        if (disposed) return;
        const sorted = newestFirst(loaded);
        setConversations(sorted);
        setNotifications(loadedNotifications);
        // A full page load always begins as a fresh, unsaved conversation. Existing
        // conversations remain available from history and a new server record is
        // created only when the visitor sends their first message.
        setSelectedConversationId(null);
        showWelcomeMessage();
        setWorkspaceState(emptyWorkspaceState());
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
    };
  }, [showWelcomeMessage]);

  useEffect(() => {
    if (!isOpening) return;
    const timeout = window.setTimeout(
      () => setIsOpening(false),
      OPENING_SPLASH_DURATION_MS,
    );
    return () => window.clearTimeout(timeout);
  }, [isOpening]);

  useEffect(() => {
    if (isOpening) return;
    const frame = requestAnimationFrame(() => composerRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [isOpening]);

  useEffect(() => {
    if (isOpening) return;
    if (latestResponse !== WELCOME_MESSAGE) return;
    setIsPresentingWelcome(true);
    const timeout = window.setTimeout(
      () => setIsPresentingWelcome(false),
      WELCOME_PRESENTATION_MS,
    );
    return () => window.clearTimeout(timeout);
  }, [isOpening, latestResponse, welcomePresentationId]);

  useEffect(() => {
    let inactivityTimer = window.setTimeout(startNewConversation, INACTIVITY_TIMEOUT_MS);

    function resetInactivityTimer() {
      window.clearTimeout(inactivityTimer);
      inactivityTimer = window.setTimeout(startNewConversation, INACTIVITY_TIMEOUT_MS);
    }

    const activityEvents = [
      "keydown",
      "pointerdown",
      "pointermove",
      "scroll",
      "touchstart",
    ] as const;
    activityEvents.forEach((eventName) =>
      window.addEventListener(eventName, resetInactivityTimer, { passive: true }),
    );

    return () => {
      window.clearTimeout(inactivityTimer);
      activityEvents.forEach((eventName) =>
        window.removeEventListener(eventName, resetInactivityTimer),
      );
    };
  }, [startNewConversation]);

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
        isOpening ||
        historyOpen ||
        aboutOpen ||
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
  }, [aboutOpen, historyOpen, isOpening]);

  useEffect(() => {
    if (!historyOpen) return;

    const previouslyFocused = document.activeElement;
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const frame = requestAnimationFrame(() => {
      historyRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    });

    function handleDrawerKeys(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setHistoryOpen(false);
        return;
      }
      if (event.key !== "Tab" || !historyRef.current) return;

      const focusable = Array.from(
        historyRef.current.querySelectorAll<HTMLElement>(
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
  }, [historyOpen]);

  async function sendMessage(
    suggestedMessage?: string,
    existingConversationId?: string,
    operationAlreadyClaimed = false,
  ): Promise<void> {
    const isSuggestedPrompt = suggestedMessage !== undefined;
    const visibleText = (suggestedMessage ?? message).trim();
    const pendingUploads = isSuggestedPrompt ? [] : uploads;
    if (
      (!visibleText && pendingUploads.length === 0) ||
      isInitializing ||
      isRunning ||
      isUploading ||
      (!operationAlreadyClaimed && operationInFlight.current)
    ) {
      return;
    }
    if (!operationAlreadyClaimed) operationInFlight.current = true;
    const text = messageWithUploads(visibleText, pendingUploads);

    if (!isSuggestedPrompt) {
      setMessage("");
      setUploads([]);
      setUploadError(null);
    }
    setIsRunning(true);
    setIsStreamingText(false);
    setCurrentAction("Preparing conversation context");
    setActivities([]);
    if (
      taQuestion?.status === "queued" ||
      taQuestion?.status === "sent" ||
      taQuestion?.status === "answered" ||
      taQuestion?.status === "cancelled"
    ) {
      setTAQuestion(null);
    }
    setLatestResponse("");
    let conversationId = existingConversationId ?? selectedConversationId;
    let receivedError = false;
    let writingActivityRecorded = false;
    let streamedText = "";
    const controller = new AbortController();
    activeRun.current = controller;

    try {
      if (!conversationId) {
        const title = visibleText || `Uploaded ${pendingUploads[0]?.filename ?? "file"}`;
        const created = await createConversation(titleFromMessage(title));
        conversationId = created.id;
        setSelectedConversationId(created.id);
        setConversations((current) => newestFirst([created, ...current]));
      }
      const activeConversationId = conversationId;

      const handleStreamEvent = (event: AgentStreamEvent) => {
        if (controller.signal.aborted) return;
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
          streamedText += event.text;
          setLatestResponse(streamedText);
        } else if (event.kind === "text_final") {
          streamedText = event.text;
          setLatestResponse(event.text);
        } else if (event.kind === "activity") {
          setActivities((current) => [...current, event.activity]);
          setCurrentAction(event.activity.label);
        } else if (event.kind === "workspace") {
          setWorkspaceState((current) => {
            try {
              return builtInComponentRegistry.apply(current, event.command);
            } catch {
              return current;
            }
          });
        } else if (event.kind === "application_submitted") {
          setWorkspaceState((current) => {
            const applicationPanels = current.panels.filter(
              (panel) =>
                panel.resourceUri === "course://application" ||
                panel.state.document_kind === "course-application",
            );
            let next = current;
            for (const panel of applicationPanels) {
              next = builtInComponentRegistry.apply(next, {
                type: "close",
                panel_id: panel.id,
              });
              void applyWorkspacePanelAction(activeConversationId, "close", panel.id).catch(
                () => undefined,
              );
            }
            return next;
          });
          applicationReturnResponse.current = null;
        } else if (event.kind === "ta_question_confirmation") {
          setTAQuestion(event.confirmation);
        } else if (event.kind === "done") {
          setActivities((current) => [
            ...current,
            { kind: "complete", label: "Agent run complete" },
          ]);
        } else if (event.kind === "error") {
          receivedError = true;
          setLatestResponse(CONNECTION_ERROR);
          setActivities((current) => [
            ...current,
            { kind: "error", label: "Agent run failed" },
          ]);
        }
      };

      await streamAgentRun(conversationId, text, handleStreamEvent, controller.signal);
      if (!receivedError) {
        setCurrentAction("Presenting response");
      }
      try {
        await loadConversationList();
      } catch {
        // The completed answer remains usable if refreshing navigation fails.
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setLatestResponse(CONNECTION_ERROR);
      }
    } finally {
      activeRun.current = null;
      operationInFlight.current = false;
      setCurrentAction(null);
      setIsStreamingText(false);
      setIsRunning(false);
      requestAnimationFrame(() => composerRef.current?.focus());
    }
  }

  async function startApplication(): Promise<void> {
    if (isInitializing || isRunning || isUploading || operationInFlight.current) return;
    operationInFlight.current = true;
    applicationReturnResponse.current = latestResponse;
    setAboutOpen(false);
    let conversationId = selectedConversationId;
    try {
      if (!conversationId) {
        const created = await createConversation("Course application");
        conversationId = created.id;
        setSelectedConversationId(created.id);
        setConversations((current) => newestFirst([created, ...current]));
      }
      const event = await ensureApplicationDraft(conversationId);
      setWorkspaceState((current) =>
        builtInComponentRegistry.apply(current, event.payload.command),
      );
      void sendMessage(HEADER_PROMPTS[0].message, conversationId, true);
    } catch {
      setLatestResponse(CONNECTION_ERROR);
      operationInFlight.current = false;
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  async function handleFileSelection(fileList: FileList | null): Promise<void> {
    const files = Array.from(fileList ?? []);
    if (files.length === 0) return;
    const validationError = uploadValidationError(files);
    if (validationError) {
      setUploadError(validationError);
      if (fileInputRef.current) fileInputRef.current.value = "";
      requestAnimationFrame(() => composerRef.current?.focus());
      return;
    }
    setIsUploading(true);
    setPendingUploadCount(files.length);
    setUploadError(null);
    try {
      const stored = await Promise.all(files.map((file) => uploadFile(file)));
      setUploads((current) => [...current, ...stored]);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Upload failed");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
      setIsUploading(false);
      setPendingUploadCount(0);
      requestAnimationFrame(() => composerRef.current?.focus());
    }
  }

  const canDropFiles =
    !aboutOpen &&
    !historyOpen &&
    !isInitializing &&
    !isRunning &&
    !isUploading &&
    !awaitingTAQuestionAction;

  function dragContainsFiles(event: DragEvent<HTMLDivElement>): boolean {
    return Array.from(event.dataTransfer.types).includes("Files");
  }

  function handleFileDragEnter(event: DragEvent<HTMLDivElement>): void {
    if (!dragContainsFiles(event)) return;
    event.preventDefault();
    if (canDropFiles) setIsFileDragActive(true);
  }

  function handleFileDragOver(event: DragEvent<HTMLDivElement>): void {
    if (!dragContainsFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = canDropFiles ? "copy" : "none";
  }

  function handleFileDragLeave(event: DragEvent<HTMLDivElement>): void {
    if (
      event.relatedTarget instanceof Node &&
      event.currentTarget.contains(event.relatedTarget)
    ) {
      return;
    }
    setIsFileDragActive(false);
  }

  function handleFileDrop(event: DragEvent<HTMLDivElement>): void {
    if (!dragContainsFiles(event)) return;
    event.preventDefault();
    setIsFileDragActive(false);
    if (canDropFiles) void handleFileSelection(event.dataTransfer.files);
  }

  async function toggleAbout(): Promise<void> {
    if (aboutOpen) {
      setAboutOpen(false);
      requestAnimationFrame(() => composerRef.current?.focus());
      return;
    }
    setHistoryOpen(false);
    setAboutOpen(true);
    setSyllabusContent(null);
    setSyllabusError(null);
    setSyllabusLoading(true);
    try {
      const resource = await getCourseResourceContent("course://syllabus");
      setSyllabusContent(new TextDecoder().decode(resource.data));
    } catch {
      setSyllabusError("The syllabus could not be loaded. Please try again.");
    } finally {
      setSyllabusLoading(false);
    }
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthSubmitting(true);
    setAuthError(null);
    try {
      const nextPrincipal = await login(username.trim(), accessCode);
      setPrincipal(nextPrincipal);
      setAccessCode("");
      const [loaded, loadedNotifications] = await Promise.all([
        loadConversationList(),
        notificationsFor(nextPrincipal),
      ]);
      setNotifications(loadedNotifications);
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
      setNotifications([]);
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

  async function handleWorkspacePanelAction(
    action: "focus" | "close",
    panelId: string,
  ): Promise<void> {
    if (!selectedConversationId) return;
    try {
      const event = await applyWorkspacePanelAction(
        selectedConversationId,
        action,
        panelId,
      );
      setWorkspaceState((current) =>
        builtInComponentRegistry.apply(current, event.payload.command),
      );
    } catch {
      setActivities((current) => [
        ...current,
        { kind: "error", label: "Workspace action failed" },
      ]);
    }
  }

  async function handleTAQuestionAction(
    action: "send" | "cancel",
    reporterVisibility: "named" | "anonymous",
  ): Promise<void> {
    if (!selectedConversationId || !taQuestion || taQuestion.status === "submitting") return;
    setTAQuestion((current) => (current ? { ...current, status: "submitting" } : null));
    try {
      const event = await confirmTAQuestion(
        selectedConversationId,
        taQuestion.id,
        action,
        reporterVisibility,
      );
      setTAQuestion((current) => applyTAQuestionEvent(current, event));
      await runAgentContinuation(selectedConversationId, event.id);
      try {
        await loadConversationList();
      } catch {
        // The confirmed action remains authoritative if navigation refresh fails.
      }
    } catch {
      setTAQuestion((current) => (current ? { ...current, status: "error" } : null));
    }
  }

  async function runAgentContinuation(
    conversationId: string,
    triggerEventId: string,
  ): Promise<void> {
    setLatestResponse("");
    setIsRunning(true);
    setCurrentAction("Continuing conversation");
    setActivities([]);
    try {
      const continuation = await continueAgentAfterEvent(conversationId, triggerEventId);
      setLatestResponse(continuation.output_text);
      setActivities([{ kind: "complete", label: "Agent run complete" }]);
      try {
        const detail = await getConversation(conversationId);
        setWorkspaceState(workspaceFromEvents(detail.events));
        setTAQuestion(projectTAQuestionEvents(detail.events));
      } catch {
        // The generated continuation remains usable if projection refresh fails.
      }
    } catch {
      setTAQuestion(null);
      setLatestResponse(CONNECTION_ERROR);
      setActivities([{ kind: "error", label: "Agent run failed" }]);
    } finally {
      setIsRunning(false);
      setCurrentAction(null);
      requestAnimationFrame(() => composerRef.current?.focus());
    }
  }

  async function handleNotificationRead(notificationId: string): Promise<void> {
    try {
      await markNotificationRead(notificationId);
      setNotifications((current) =>
        current.filter((notification) => notification.id !== notificationId),
      );
    } catch {
      // Keep the unread update visible when acknowledgement could not be saved.
    }
  }

  async function handleCloseWorkspace(): Promise<void> {
    const panels = workspaceState.panels;
    const isApplicationWorkspace = panels.some(
      (panel) =>
        panel.resourceUri === "course://application" ||
        panel.state.document_kind === "course-application",
    );
    if (isApplicationWorkspace) {
      activeRun.current?.abort();
    }
    setWorkspaceState(emptyWorkspaceState());
    if (isApplicationWorkspace) {
      setActivities([]);
      setCurrentAction(null);
      setIsStreamingText(false);
      const previousResponse = applicationReturnResponse.current;
      if (previousResponse && previousResponse !== WELCOME_MESSAGE) {
        setLatestResponse(
          `${previousResponse}\n\nTo continue, send a message to the Course Agent.`,
        );
      } else {
        showWelcomeMessage();
      }
      applicationReturnResponse.current = null;
    }
    if (!selectedConversationId) return;
    try {
      await Promise.all(
        panels.map((panel) =>
          applyWorkspacePanelAction(selectedConversationId, "close", panel.id),
        ),
      );
    } catch {
      setActivities((current) => [
        ...current,
        { kind: "error", label: "Workspace could not be closed" },
      ]);
    }
  }

  async function handleWorkspaceInteraction(
    panelId: string,
    action: string,
    value: JsonValue,
  ): Promise<void> {
    if (!selectedConversationId) return;
    if (
      action !== "calendar.select_event" &&
      action !== "calendar.change_view" &&
      action !== "document.change_page" &&
      action !== "document.find_text" &&
      action !== "page_cards.select" &&
      action !== "visual.change" &&
      action !== "draft.change"
    ) {
      return;
    }
    try {
      const event = await recordWorkspaceInteraction(
        selectedConversationId,
        panelId,
        action,
        value,
      );
      if (action !== "draft.change") return;
      setWorkspaceState((current) =>
        builtInComponentRegistry.apply(current, event.payload.command),
      );
    } catch (error) {
      if (action === "draft.change") throw error;
      setActivities((current) => [
        ...current,
        { kind: "error", label: "Workspace interaction was not saved" },
      ]);
    }
  }

  async function handleBrowserScroll(
    panelId: string,
    sessionId: string,
    deltaY: number,
  ): Promise<void> {
    if (!selectedConversationId) return;
    try {
      const event = await scrollBrowserSession(
        selectedConversationId,
        panelId,
        sessionId,
        deltaY,
      );
      setWorkspaceState((current) =>
        builtInComponentRegistry.apply(current, event.payload.command),
      );
    } catch {
      setActivities((current) => [
        ...current,
        { kind: "error", label: "Browser session could not be scrolled" },
      ]);
    }
  }

  async function handleBrowserActivate(
    panelId: string,
    sessionId: string,
    x: number,
    y: number,
  ): Promise<void> {
    if (!selectedConversationId) return;
    try {
      const event = await clickBrowserSession(
        selectedConversationId,
        panelId,
        sessionId,
        x,
        y,
      );
      setWorkspaceState((current) =>
        builtInComponentRegistry.apply(current, event.payload.command),
      );
    } catch {
      setActivities((current) => [
        ...current,
        { kind: "error", label: "Browser link could not be opened" },
      ]);
    }
  }

  async function handleBrowserResize(
    panelId: string,
    sessionId: string,
    width: number,
    height: number,
  ): Promise<void> {
    if (!selectedConversationId) return;
    try {
      const event = await resizeBrowserSession(
        selectedConversationId,
        panelId,
        sessionId,
        width,
        height,
      );
      setWorkspaceState((current) =>
        builtInComponentRegistry.apply(current, event.payload.command),
      );
    } catch {
      setActivities((current) => [
        ...current,
        { kind: "error", label: "Browser viewport could not be resized" },
      ]);
    }
  }

  const isWelcomePresentationActive =
    !isOpening && latestResponse === WELCOME_MESSAGE && isPresentingWelcome;
  return (
    <div
      className="course-agent"
      data-about-open={aboutOpen}
      data-file-drag-active={isFileDragActive}
      data-opening={isOpening}
      data-workspace-open={!aboutOpen && workspaceState.panels.length > 0}
      onDragEnter={handleFileDragEnter}
      onDragLeave={handleFileDragLeave}
      onDragOver={handleFileDragOver}
      onDrop={handleFileDrop}
    >
      {isOpening ? (
        <section
          aria-label="Course introduction"
          className="opening-splash"
          data-testid="opening-splash"
        >
          <h1 className="opening-splash-title">{COURSE_TITLE}</h1>
        </section>
      ) : null}
      <div
        className="course-agent-interface"
        data-testid="course-agent-interface"
        inert={isOpening ? true : undefined}
      >
      <header className="agent-header">
        <div className="header-left">
          <div aria-label="MIT and MIT Media Lab" className="institutional-marks">
            <button aria-label="MIT" onClick={startNewConversation} type="button">
              <img alt="" className="mit-mark" src="/mit-logo.svg" />
            </button>
            <button
              aria-label="MIT Media Lab"
              onClick={startNewConversation}
              type="button"
            >
              <img alt="" className="media-lab-mark" src="/media-lab-logo.svg" />
            </button>
          </div>
        </div>
        {workspaceState.panels.length === 0 || aboutOpen ? (
          <nav aria-label="Course shortcuts" className="header-actions">
            {HEADER_PROMPTS.map((prompt) => (
              <Button
                className="header-prompt"
                disabled={
                  isInitializing || isRunning || isUploading || awaitingTAQuestionAction
                }
                key={prompt.label}
                onClick={() =>
                  prompt.label === "Apply"
                    ? void startApplication()
                    : (setAboutOpen(false), void sendMessage(prompt.message))
                }
              >
                {prompt.label}
              </Button>
            ))}
            <Button
              aria-current={aboutOpen ? "page" : undefined}
              className="about-link"
              onClick={() => void toggleAbout()}
            >
              About
            </Button>
            <Button
              aria-expanded={historyOpen}
              aria-haspopup="dialog"
              className="logs-link"
              onClick={() => {
                setAboutOpen(false);
                setHistoryOpen(true);
              }}
            >
              Your logs
            </Button>
          </nav>
        ) : null}
      </header>

      {aboutOpen ? (
        <SyllabusPage
          content={syllabusContent}
          error={syllabusError}
          loading={syllabusLoading}
        />
      ) : (
        <>
          <CourseNotifications
            notifications={notifications}
            onRead={(notificationId) => void handleNotificationRead(notificationId)}
          />
          <main className="workspace-shell" data-testid="workspace-shell">
        <section aria-atomic="false" aria-live="polite" className="response-stage">
          <MorphingLineFigure
            active={
              isInitializing ||
              isRunning ||
              isStreamingText ||
              isWelcomePresentationActive ||
              currentAction !== null
            }
          />
          <div className="response-agent-line" data-testid="response-agent-line">
            <span className="response-agent-name">Course Agent</span>
            <ActivityTrace activities={activities} currentLabel={currentAction} />
          </div>
          {latestResponse ? (
            <AgentResponse
              initialCharacterDelayMs={
                isWelcomePresentationActive ? WELCOME_MORPH_DELAY_MS : 0
              }
              key={
                latestResponse === WELCOME_MESSAGE
                  ? `welcome-${welcomePresentationId}`
                  : "agent-response"
              }
              staggerCharacters={latestResponse === WELCOME_MESSAGE}
              streaming={isStreamingText || isWelcomePresentationActive}
              text={latestResponse}
            />
          ) : null}
          {taQuestion ? (
            <TAQuestionConfirmation
              confirmation={taQuestion}
              onAction={(action, reporterVisibility) =>
                void handleTAQuestionAction(action, reporterVisibility)
              }
            />
          ) : null}
        </section>
        {workspaceState.panels.length > 0 ? (
          <Workspace
            conversationId={selectedConversationId!}
            onBrowserActivate={handleBrowserActivate}
            onBrowserResize={handleBrowserResize}
            onBrowserScroll={handleBrowserScroll}
            onInteraction={handleWorkspaceInteraction}
            onCloseWorkspace={handleCloseWorkspace}
            onPanelAction={handleWorkspacePanelAction}
            onSubmitApplication={() => void sendMessage("Please submit my application.")}
            state={workspaceState}
          />
        ) : null}
          </main>

          <form
        aria-label="Message Course Agent"
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          void sendMessage();
        }}
      >
        <div className="composer-inner">
          <input
            ref={fileInputRef}
            accept=".csv,.json,.md,.pdf,.txt,image/gif,image/jpeg,image/png,image/webp"
            className="visually-hidden"
            multiple
            onChange={(event) => void handleFileSelection(event.target.files)}
            type="file"
          />
          <div
            aria-busy={isUploading}
            className="composer-entry"
            data-drop-active={isFileDragActive}
            data-uploading={isUploading}
          >
            {isFileDragActive || isUploading ? (
              <div className="composer-drop-state" role="status">
                <span aria-hidden="true" className="composer-drop-icon">
                  <svg viewBox="0 0 24 24">
                    <path d="M12 15V4m0 0L8 8m4-4 4 4" />
                    <path d="M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" />
                  </svg>
                </span>
                <span className="composer-drop-copy">
                  <strong>
                    {isUploading
                      ? `Uploading ${pendingUploadCount} ${
                          pendingUploadCount === 1 ? "file" : "files"
                        }`
                      : "Drop files to attach"}
                  </strong>
                  <span>
                    {isUploading
                      ? "Preparing your attachment"
                      : "Images, PDF, text, CSV, JSON, or Markdown"}
                  </span>
                </span>
                {isUploading ? (
                  <span aria-hidden="true" className="upload-progress-track">
                    <span />
                  </span>
                ) : null}
              </div>
            ) : null}
            {uploads.length > 0 ? (
              <ul aria-label="Temporary uploads" className="upload-list">
                {uploads.map((upload) => (
                  <li key={upload.id}>
                    <span>{upload.filename}</span>
                    <button
                      aria-label={`Remove ${upload.filename}`}
                      onClick={() =>
                        setUploads((current) =>
                          current.filter((item) => item.id !== upload.id),
                        )
                      }
                      type="button"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            <textarea
              ref={composerRef}
              aria-label="Message"
              autoComplete="off"
              autoFocus={!isOpening}
              className="composer-text"
              disabled={isInitializing || isRunning || isUploading || awaitingTAQuestionAction}
              enterKeyHint="send"
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder="Start typing to interact with the agent"
              rows={1}
              spellCheck
              value={message}
            />
            {uploadError ? (
              <p className="upload-error" role="alert">
                {uploadError}
              </p>
            ) : null}
            <div className="composer-actions">
              <button
                aria-label="Attach files"
                className="attachment-button"
                disabled={
                  isInitializing || isRunning || isUploading || awaitingTAQuestionAction
                }
                onClick={() => fileInputRef.current?.click()}
                type="button"
              >
                <svg aria-hidden="true" viewBox="0 0 24 24">
                  <path d="m8.5 12.5 6.8-6.8a3 3 0 1 1 4.2 4.2l-8.2 8.2a5 5 0 0 1-7.1-7.1l7.5-7.5" />
                </svg>
                {isUploading ? "Uploading" : "Attach"}
              </button>
            </div>
          </div>
        </div>
        <button aria-hidden="true" className="visually-hidden" tabIndex={-1} type="submit">
          Send
        </button>
          </form>
        </>
      )}

      {historyOpen ? (
        <div
          className="drawer-backdrop"
          onClick={() => setHistoryOpen(false)}
          role="presentation"
        >
          <aside
            ref={historyRef}
            aria-label="Chat history"
            aria-modal="true"
            className="agent-drawer"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
          >
            <div className="drawer-heading">
              <span>Course Agent</span>
              <Button
                aria-label="Hide chat history"
                className="drawer-close"
                onClick={() => setHistoryOpen(false)}
              >
                <CloseIcon />
              </Button>
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
                  <p className="drawer-label">Course login</p>
                  <TextInput
                    autoComplete="username"
                    label="Email or username"
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
    </div>
  );
}
