import {
  BrowserViewer,
  Calendar,
  DocumentViewer,
  DraftDocument,
  PageCards,
  VisualComposition,
  WebpageViewer,
  normalizeCalendarData,
  normalizeVisualElements,
  type DocumentResource,
  type DraftDocumentField,
  type DraftDocumentStatus,
  type DraftFieldInputType,
  type DraftFieldStatus,
  type PageCardItem,
  type TextHighlightAnchor,
} from "@class-agent/ui";
import type { JsonObject, JsonValue, WorkspacePanel, WorkspaceState } from "@class-agent/workspace";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  applicantPhotoUrl,
  browserSnapshotUrl,
  browserStreamUrl,
  browserPreviewSnapshotUrl,
  courseResourceAssetUrl,
  getCourseResourceContent,
  getMyAssignmentFeedback,
  getMyWeeklyBuildGrades,
  ApiError,
  type CourseResourceContent,
  type WeeklyFeedback,
  type WeeklyBuildGrade,
} from "./api.js";

import { PeerDiscoveryPanel } from "./PeerDiscoveryPanel.js";
import { StreamingBrowserViewer } from "./StreamingBrowserViewer.js";
import { splitWeeklyFeedback } from "./weeklyFeedback.js";

interface WorkspaceProps {
  browserControlsReady?: boolean;
  conversationId: string;
  historical?: boolean;
  state: WorkspaceState;
  onPanelAction: (action: "focus" | "close", panelId: string) => Promise<void>;
  onCloseWorkspace: () => Promise<void>;
  onCheckAssignment?: ((resourceUri: string) => void) | undefined;
  onOpenAssignment?: ((assignmentId: string) => void) | undefined;
  onSubmitApplication?: (() => void) | undefined;
  onInteraction: (panelId: string, action: string, value: JsonValue) => Promise<void>;
  onBrowserScroll: (panelId: string, sessionId: string, deltaY: number) => Promise<void>;
  onBrowserActivate: (
    panelId: string,
    sessionId: string,
    x: number,
    y: number,
  ) => Promise<void>;
  onBrowserResize: (
    panelId: string,
    sessionId: string,
    width: number,
    height: number,
  ) => Promise<void>;
}

const DEFAULT_COMPONENT_RESOURCES: Readonly<Record<string, string>> = {
  calendar: "course://schedule",
};
const ASSIGNMENT_RESOURCE_URI = /^course:\/\/assignment\/[a-z0-9]+(?:-[a-z0-9]+)*$/;

function FeedbackCard({
  assignmentId,
  title,
  feedback,
  error = false,
  loading = false,
  onOpenAssignment,
}: {
  assignmentId: string;
  title: string;
  feedback: WeeklyFeedback | null;
  error?: boolean;
  loading?: boolean;
  onOpenAssignment?: ((assignmentId: string) => void) | undefined;
}) {
  const sections = feedback ? splitWeeklyFeedback(feedback.feedback) : null;
  const CardHeading = onOpenAssignment ? "h3" : "h2";
  const SectionHeading = onOpenAssignment ? "h4" : "h3";
  return (
    <article aria-label={title === "Weekly build feedback" ? title : `${title} feedback`} className="workspace-feedback-card">
      <header className="workspace-feedback-card-header">
        <div>
          <span className="workspace-feedback-eyebrow">TA feedback</span>
          <CardHeading>{title}</CardHeading>
          {feedback ? <p>{feedback.reviewer} · {feedback.date}</p> : null}
        </div>
        {onOpenAssignment ? (
          <button onClick={() => onOpenAssignment(assignmentId)} type="button">
            Open assignment <span aria-hidden="true">↗</span>
          </button>
        ) : null}
      </header>
      {loading ? <p className="workspace-feedback-message">Loading feedback…</p> : null}
      {error ? <p className="workspace-feedback-message">Feedback could not be loaded. Please reopen this page.</p> : null}
      {!loading && !error && feedback === null ? (
        <p className="workspace-feedback-message">No TA feedback has been posted for this build yet.</p>
      ) : null}
      {sections ? (
        <div className="workspace-feedback-card-body">
          {sections.comments ? (
            <section aria-label="TA comments section" className="workspace-feedback-comments">
              <SectionHeading>Comments</SectionHeading>
              <DocumentViewer resource={{
                uri: `course://grades/mine/assignments/${assignmentId}/comments`,
                title: "Comments",
                mediaType: "text/markdown",
                data: new TextEncoder().encode(sections.comments.replaceAll("\n", "  \n")),
              }} />
            </section>
          ) : null}
          {sections.checklist.length ? (
            <section aria-label="Grading checklist" className="workspace-feedback-checklist">
              <SectionHeading>Grading checklist</SectionHeading>
              <ul>
                {sections.checklist.map((item, index) => (
                  <li data-status={item.status} key={`${index}-${item.text}`}>
                    <span aria-hidden="true" className="workspace-feedback-mark">
                      {item.status === "met" ? "✓" : item.status === "unmet" ? "✗" : "•"}
                    </span>
                    <span className="visually-hidden">
                      {item.status === "met" ? "Met: " : item.status === "unmet" ? "Not met: " : "Item: "}
                    </span>
                    <span>{item.text}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function AssignmentFeedback({
  assignmentId,
  title = "Weekly build feedback",
  showLoading = false,
  onOpenAssignment,
}: {
  assignmentId: string;
  title?: string;
  showLoading?: boolean;
  onOpenAssignment?: ((assignmentId: string) => void) | undefined;
}) {
  const [feedback, setFeedback] = useState<WeeklyFeedback | null | undefined>(undefined);
  const [hidden, setHidden] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    setFeedback(undefined);
    setHidden(false);
    setError(false);
    void getMyAssignmentFeedback(assignmentId).then(
      ({ feedback: note }) => { if (active) setFeedback(note); },
      (reason: unknown) => {
        if (!active) return;
        if (reason instanceof ApiError && reason.status === 404) setHidden(true);
        else setError(true);
      },
    );
    return () => { active = false; };
  }, [assignmentId]);
  if ((hidden && !showLoading) || (feedback === undefined && !error && !showLoading)) return null;
  return (
    <section aria-label="Weekly build feedback" className="workspace-assignment-feedback">
      <FeedbackCard
        assignmentId={assignmentId}
        error={error || hidden}
        feedback={feedback ?? null}
        loading={feedback === undefined && !error && !hidden}
        onOpenAssignment={onOpenAssignment}
        title={title}
      />
    </section>
  );
}

function GradingOverview({ onOpenAssignment }: {
  onOpenAssignment?: ((assignmentId: string) => void) | undefined;
}) {
  const [assignments, setAssignments] = useState<WeeklyBuildGrade[] | null>(null);
  useEffect(() => {
    let active = true;
    void getMyWeeklyBuildGrades().then(
      ({ assignments: items }) => { if (active) setAssignments(items); },
      () => { if (active) setAssignments(null); },
    );
    return () => { active = false; };
  }, []);
  if (!assignments) return null;
  return (
    <section aria-label="Weekly build feedback" className="workspace-grading-feedback">
      <h2>Weekly build feedback</h2>
      <p>TA feedback here covers weekly builds. Open an assignment to see its feedback beneath the instructions too.</p>
      <div className="workspace-grading-cards">
        {assignments.map((assignment) => (
          assignment.has_feedback ? (
            <AssignmentFeedback
              assignmentId={assignment.assignment_id}
              key={assignment.assignment_id}
              onOpenAssignment={onOpenAssignment}
              showLoading
              title={assignment.title}
            />
          ) : (
            <FeedbackCard
              assignmentId={assignment.assignment_id}
              feedback={null}
              key={assignment.assignment_id}
              onOpenAssignment={onOpenAssignment}
              title={assignment.title}
            />
          )
        ))}
      </div>
    </section>
  );
}

function gradingPolicyResource(resource: DocumentResource): DocumentResource {
  if (resource.mediaType !== "text/markdown") return resource;
  const content = new TextDecoder().decode(resource.data);
  const start = /^##\s+.*Assignments and Evaluation.*$/im.exec(content);
  if (!start) return resource;
  const remaining = content.slice(start.index);
  const next = /^##\s+/m.exec(remaining.slice(start[0].length));
  const section = next
    ? remaining.slice(0, start[0].length + next.index)
    : remaining;
  return {
    ...resource,
    data: new TextEncoder().encode(`# Grading\n\n${section.trim()}\n`),
    title: "Grading",
    uri: `${resource.uri}#grading`,
  };
}

function CloseIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="9.25" />
      <path d="m9 9 6 6m0-6-6 6" />
    </svg>
  );
}

function stringProp(props: JsonObject, name: string): string | undefined {
  const value = props[name];
  return typeof value === "string" ? value : undefined;
}

function numberProp(props: JsonObject, name: string): number | undefined {
  const value = props[name];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function resolveVisualCourseAssets(
  value: JsonValue | undefined,
  resourceUri: string | undefined,
): JsonValue | undefined {
  if (!Array.isArray(value)) return value;
  return value.map((element) => {
    if (
      element &&
      typeof element === "object" &&
      !Array.isArray(element) &&
      element.type === "image" &&
      typeof element.url === "string"
    ) {
      const protectedUrl = applicantPhotoUrl(element.url);
      if (protectedUrl) return { ...element, url: protectedUrl };
    }
    if (
      !element ||
      typeof element !== "object" ||
      Array.isArray(element) ||
      element.type !== "image" ||
      typeof element.asset_id !== "string" ||
      !resourceUri
    ) {
      return element;
    }
    const { asset_id: assetId, ...resolved } = element;
    return {
      ...resolved,
      url: courseResourceAssetUrl(resourceUri, assetId),
    };
  });
}

function draftDocumentFields(value: JsonValue | undefined): DraftDocumentField[] | null {
  if (!Array.isArray(value)) return null;
  const statuses = new Set<DraftFieldStatus>([
    "missing",
    "candidate",
    "inferred",
    "confirmed",
  ]);
  const fields: DraftDocumentField[] = [];
  const inputTypes = new Set<DraftFieldInputType>([
    "text",
    "email",
    "url",
    "year",
    "multiline",
    "attachment",
  ]);
  for (const item of value) {
    if (!item || typeof item !== "object" || Array.isArray(item)) return null;
    if (
      typeof item.id !== "string" ||
      typeof item.label !== "string" ||
      typeof item.status !== "string" ||
      !statuses.has(item.status as DraftFieldStatus)
    ) {
      return null;
    }
    const field: DraftDocumentField = {
      id: item.id,
      label: item.label,
      status: item.status as DraftFieldStatus,
    };
    if (typeof item.value === "string") field.value = item.value;
    if (typeof item.source === "string") field.source = item.source;
    if (typeof item.help_text === "string") field.helpText = item.help_text;
    if (typeof item.validation_error === "string") {
      field.validationError = item.validation_error;
    }
    if (typeof item.input_type === "string") {
      if (!inputTypes.has(item.input_type as DraftFieldInputType)) return null;
      field.inputType = item.input_type as DraftFieldInputType;
    }
    if (item.options !== undefined) {
      if (
        !Array.isArray(item.options) ||
        item.options.length === 0 ||
        !item.options.every((option) => typeof option === "string")
      ) {
        return null;
      }
      field.options = item.options;
    }
    fields.push(field);
  }
  return fields;
}

function highlightProp(value: JsonValue | undefined): TextHighlightAnchor | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const uri = value.resource_uri;
  const page = value.page;
  const quote = value.quote;
  if (typeof uri !== "string" || typeof page !== "number" || typeof quote !== "string") {
    return undefined;
  }
  const anchor: TextHighlightAnchor = { resourceUri: uri, page, quote };
  if (typeof value.prefix === "string") anchor.prefix = value.prefix;
  if (typeof value.suffix === "string") anchor.suffix = value.suffix;
  return anchor;
}

function pageCardItems(
  value: JsonValue | undefined,
  conversationId: string,
): PageCardItem[] | null {
  if (!Array.isArray(value)) return null;
  const items: PageCardItem[] = [];
  for (const raw of value) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    if (
      typeof raw.id !== "string" ||
      typeof raw.url !== "string" ||
      typeof raw.title !== "string"
    ) {
      return null;
    }
    const item: PageCardItem = { id: raw.id, url: raw.url, title: raw.title };
    if (typeof raw.description === "string") item.description = raw.description;
    if (typeof raw.image_url === "string") item.imageUrl = raw.image_url;
    if (typeof raw.preview_id === "string" && typeof raw.revision === "number") {
      item.capture = true;
      item.imageUrl = browserPreviewSnapshotUrl(
        conversationId,
        raw.preview_id,
        raw.revision,
      );
    }
    items.push(item);
  }
  return items;
}

function ResourcePanel({
  browserControlsReady,
  conversationId,
  historical,
  panel,
  onBrowserActivate,
  onBrowserScroll,
  onBrowserResize,
  onInteraction,
  onCheckAssignment,
  onOpenAssignment,
  onSubmitApplication,
}: {
  browserControlsReady: boolean;
  conversationId: string;
  historical: boolean;
  panel: WorkspacePanel;
  onBrowserActivate: (
    panelId: string,
    sessionId: string,
    x: number,
    y: number,
  ) => Promise<void>;
  onBrowserScroll: (panelId: string, sessionId: string, deltaY: number) => Promise<void>;
  onBrowserResize: (
    panelId: string,
    sessionId: string,
    width: number,
    height: number,
  ) => Promise<void>;
  onInteraction: (panelId: string, action: string, value: JsonValue) => Promise<void>;
  onCheckAssignment?: ((resourceUri: string) => void) | undefined;
  onOpenAssignment?: ((assignmentId: string) => void) | undefined;
  onSubmitApplication?: (() => void) | undefined;
}) {
  const [resource, setResource] = useState<CourseResourceContent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<number | null>(null);
  const pendingDraftCommit = useRef<Promise<void> | null>(null);
  const resourceUri = panel.resourceUri ?? DEFAULT_COMPONENT_RESOURCES[panel.componentId];
  const webpageUrl = stringProp(panel.props, "url");
  const webpageMode = stringProp(panel.props, "mode");
  const webpageContent = stringProp(panel.props, "content");
  const draftFields =
    panel.props.fields === undefined ? [] : draftDocumentFields(panel.props.fields);
  const draftContent = stringProp(panel.props, "content");
  const isApplicationPanel =
    panel.resourceUri === "course://application" ||
    panel.state.document_kind === "course-application";
  const assignmentResourceUri =
    typeof resourceUri === "string" && ASSIGNMENT_RESOURCE_URI.test(resourceUri)
      ? resourceUri
      : undefined;
  const isAssignmentPanel = assignmentResourceUri !== undefined;
  const applicationFields =
    isApplicationPanel && draftFields ? draftFields : null;
  const applicationProgress = applicationFields
    ? applicationFields.filter(
        (field) => field.status === "confirmed" && Boolean(field.value?.trim()),
      ).length
    : null;
  const applicationComplete =
    applicationProgress !== null && applicationProgress === applicationFields?.length;
  const commitDraftChange = (fieldId: string, value: string): Promise<void> => {
    const request = onInteraction(panel.id, "draft.change", {
      field_id: fieldId,
      value,
    });
    pendingDraftCommit.current = request;
    void request.then(
      () => {
        if (pendingDraftCommit.current === request) pendingDraftCommit.current = null;
      },
      () => {
        if (pendingDraftCommit.current === request) pendingDraftCommit.current = null;
      },
    );
    return request;
  };
  const submitAfterDraftCommit = (submit: () => void): void => {
    const pending = pendingDraftCommit.current;
    if (pending === null) {
      submit();
      return;
    }
    void pending.then(submit, () => undefined);
  };

  useEffect(() => {
    let disposed = false;
    setResource(null);
    setError(null);
    setDownloadProgress(null);
    if (
      panel.componentId === "webpage-viewer" ||
      panel.componentId === "browser-viewer" ||
      panel.componentId === "peer-discovery" ||
      panel.componentId === "page-cards" ||
      panel.componentId === "visual-composition" ||
      panel.componentId === "draft-document"
    ) {
      return;
    }
    if (!resourceUri) {
      setError("This panel does not reference a resource.");
      return () => {
        disposed = true;
      };
    }
    void getCourseResourceContent(resourceUri, (loadedBytes, totalBytes) => {
      if (!disposed && totalBytes) {
        setDownloadProgress(Math.min(100, (loadedBytes / totalBytes) * 100));
      }
    })
      .then((loaded) => {
        if (!disposed) setResource(loaded);
      })
      .catch(() => {
        if (!disposed) setError("The requested course resource could not be opened.");
      });
    return () => {
      disposed = true;
    };
  }, [panel.componentId, resourceUri]);

  const documentResource: DocumentResource | null = resource
    ? {
        uri: resource.uri,
        title: panel.title ?? "Course document",
        mediaType: resource.mediaType,
        data: resource.data,
        ...(resource.pdfDownloadUrl ? { pdfDownloadUrl: resource.pdfDownloadUrl } : {}),
      }
    : null;
  const calendarData = useMemo(() => {
    if (!resource) return null;
    try {
      const decoded = new TextDecoder().decode(resource.data);
      const source: unknown =
        resource.mediaType === "application/json" ? JSON.parse(decoded) : decoded;
      return normalizeCalendarData(source);
    } catch {
      return null;
    }
  }, [resource]);

  if (panel.componentId === "browser-viewer") {
    const sessionId = stringProp(panel.props, "session_id");
    const url = stringProp(panel.props, "url");
    const title = stringProp(panel.props, "title") ?? panel.title;
    const revision = numberProp(panel.props, "revision");
    const scrollY = numberProp(panel.props, "scroll_y");
    const viewportHeight = numberProp(panel.props, "viewport_height");
    const viewportWidth = numberProp(panel.props, "viewport_width");
    if (!sessionId || !url || !title || !revision) {
      return <p className="workspace-panel-message">The browser session is invalid.</p>;
    }
    const viewerProps = {
      controlsEnabled: browserControlsReady,
      imageUrl: browserSnapshotUrl(conversationId, sessionId, revision),
      onActivate: (x: number, y: number) => onBrowserActivate(panel.id, sessionId, x, y),
      onScroll: (deltaY: number) => onBrowserScroll(panel.id, sessionId, deltaY),
      onResize: (width: number, height: number) =>
        onBrowserResize(panel.id, sessionId, width, height),
      title,
      url,
      ...(viewportHeight === undefined ? {} : { viewportHeight }),
      ...(viewportWidth === undefined ? {} : { viewportWidth }),
      ...(scrollY === undefined ? {} : { focusScrollY: scrollY }),
    };
    return historical ? (
      <BrowserViewer {...viewerProps} />
    ) : (
      <StreamingBrowserViewer
        {...viewerProps}
        streamUrl={browserStreamUrl(conversationId, sessionId)}
      />
    );
  }

  if (panel.componentId === "webpage-viewer" && webpageUrl) {
    return (
      <WebpageViewer
        content={webpageContent}
        mode={webpageMode === "live" ? "live" : "reader"}
        title={panel.title ?? "Web page"}
        url={webpageUrl}
      />
    );
  }
  if (panel.componentId === "peer-discovery") {
    const view = panel.props.view === "memory" || panel.props.view === "coverage" ? panel.props.view : "recommendations";
    return <PeerDiscoveryPanel key={panel.id} view={view} historical={historical} />;
  }
  if (panel.componentId === "page-cards") {
    const items = pageCardItems(panel.props.items, conversationId);
    const description = stringProp(panel.props, "description");
    const heading = stringProp(panel.props, "heading") ?? panel.title;
    const selectedId = stringProp(panel.props, "selected_id");
    if (!items || items.length < 2) {
      return <p className="workspace-panel-message">The page-card data is invalid.</p>;
    }
    return (
      <PageCards
        presentation={panel.props.presentation === "thumbnails" ? "thumbnails" : "previews"}
        items={items}
        onSelect={(id) => void onInteraction(panel.id, "page_cards.select", id)}
        {...(description === undefined ? {} : { description })}
        {...(heading === undefined ? {} : { heading })}
        {...(selectedId === undefined ? {} : { selectedId })}
      />
    );
  }
  if (panel.componentId === "visual-composition") {
    const rootId = stringProp(panel.props, "root_id");
    const resolvedElements = resolveVisualCourseAssets(
      panel.props.elements,
      panel.resourceUri,
    );
    const elements = rootId
      ? normalizeVisualElements(resolvedElements, rootId)
      : null;
    if (!rootId || !elements) {
      return <p className="workspace-panel-message">The visual composition is invalid.</p>;
    }
    const title = stringProp(panel.props, "title") ?? panel.title;
    const description = stringProp(panel.props, "description");
    return (
      <VisualComposition
        elements={elements}
        rootId={rootId}
        onChange={(elementId, value) =>
          void onInteraction(panel.id, "visual.change", {
            element_id: elementId,
            value,
          })
        }
        {...(title === undefined ? {} : { title })}
        {...(description === undefined ? {} : { description })}
      />
    );
  }
  if (panel.componentId === "webpage-viewer") {
    return <p className="workspace-panel-message">The web page URL is invalid.</p>;
  }
  if (
    panel.componentId === "draft-document" &&
    draftFields &&
    (draftFields.length > 0 || draftContent)
  ) {
    const status = stringProp(panel.props, "status");
    return (
      <>
        <DraftDocument
          actionDisabled={!browserControlsReady}
          actionLabel={
            isAssignmentPanel && onCheckAssignment ? "Review my progress" : undefined
          }
          description={stringProp(panel.props, "description")}
          content={draftContent}
          fields={draftFields}
          onChange={commitDraftChange}
          status={
            status === "ready" || status === "final" || status === "submitted"
              ? (status as DraftDocumentStatus)
              : "draft"
          }
          title={stringProp(panel.props, "title") ?? panel.title ?? "Draft document"}
          onAction={
            isAssignmentPanel && onCheckAssignment
              ? () => onCheckAssignment(assignmentResourceUri)
              : undefined
          }
        />
        {isAssignmentPanel && /^week-\d+$/.test(assignmentResourceUri.slice("course://assignment/".length)) ? (
          <AssignmentFeedback assignmentId={assignmentResourceUri.slice("course://assignment/".length)} />
        ) : null}
        {applicationFields && applicationProgress !== null && onSubmitApplication ? (
          <footer className="workspace-application-submit">
            <span
              title={
                applicationComplete
                  ? undefined
                  : `${applicationProgress}/${applicationFields.length} required fields confirmed`
              }
            >
              <button
                disabled={!applicationComplete}
                onClick={() => submitAfterDraftCommit(onSubmitApplication)}
                type="button"
              >
                Submit application
              </button>
            </span>
          </footer>
        ) : null}
      </>
    );
  }
  if (panel.componentId === "draft-document") {
    return <p className="workspace-panel-message">The draft document data is invalid.</p>;
  }
  if (error) return <p className="workspace-panel-message">{error}</p>;
  if (!resource) {
    return (
      <div aria-busy="true" className="workspace-resource-loading">
        <p>
          Opening resource…
          {downloadProgress === null ? null : <span>{Math.round(downloadProgress)}%</span>}
        </p>
        <div
          aria-label="Opening resource"
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={downloadProgress === null ? undefined : Math.round(downloadProgress)}
          aria-valuetext={
            downloadProgress === null ? "Loading" : `${Math.round(downloadProgress)}% downloaded`
          }
          className="workspace-resource-loading-bar"
          data-determinate={downloadProgress !== null}
          role="progressbar"
        >
          <span
            style={
              downloadProgress === null
                ? undefined
                : { transform: `scaleX(${downloadProgress / 100})` }
            }
          />
        </div>
      </div>
    );
  }
  if (panel.componentId === "document-viewer" && documentResource) {
    if (panel.state.document_kind === "grading-overview") {
      return (
        <div className="workspace-grading-panel">
          <DocumentViewer
            resource={gradingPolicyResource(documentResource)}
          />
          <GradingOverview onOpenAssignment={onOpenAssignment} />
        </div>
      );
    }
    return (
      <>
        <DocumentViewer
          findText={stringProp(panel.props, "find_text")}
          highlight={highlightProp(panel.props.highlight)}
          page={numberProp(panel.props, "page")}
          resource={documentResource}
          onFind={(query) => void onInteraction(panel.id, "document.find_text", query)}
          onPageChange={(page) =>
            void onInteraction(panel.id, "document.change_page", page)
          }
        />
      </>
    );
  }
  if (panel.componentId === "calendar" && calendarData) {
    const view = stringProp(panel.props, "view");
    return (
      <Calendar
        data={calendarData}
        focusDate={stringProp(panel.props, "focus_date")}
        selectedEventId={stringProp(panel.props, "selected_event_id")}
        view={view === "month" ? "month" : "agenda"}
        onInteraction={(action, value) =>
          void onInteraction(panel.id, `calendar.${action}`, value)
        }
      />
    );
  }
  if (panel.componentId === "calendar") {
    return <p className="workspace-panel-message">The calendar data is invalid.</p>;
  }
  return <p className="workspace-panel-message">Unknown component.</p>;
}

export function Workspace({
  browserControlsReady = true,
  conversationId,
  historical = false,
  state,
  onPanelAction,
  onCloseWorkspace,
  onCheckAssignment,
  onOpenAssignment,
  onSubmitApplication,
  onInteraction,
  onBrowserScroll,
  onBrowserActivate,
  onBrowserResize,
}: WorkspaceProps) {
  const focused =
    state.panels.find((panel) => panel.id === state.focusedPanelId) ?? state.panels.at(-1);
  if (!focused) return null;
  const tabbed = state.panels.length > 1;
  const closeWorkspace = () => void onCloseWorkspace();
  const handleClosePointerDown = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    closeWorkspace();
  };

  return (
    <aside
      aria-label="Workspace"
      className="workspace-pane"
      data-history={historical ? "true" : undefined}
      data-tabbed={tabbed}
    >
      {tabbed ? (
        <header className="workspace-tabs">
          <div aria-label="Workspace panels" role="tablist">
            {state.panels.map((panel) => (
              <button
                aria-selected={panel.id === focused.id}
                key={panel.id}
                onClick={() => void onPanelAction("focus", panel.id)}
                role="tab"
                type="button"
              >
                {panel.title ?? panel.componentId}
              </button>
            ))}
          </div>
          <button
            aria-label="Close workspace"
            className="workspace-close"
            onClick={closeWorkspace}
            onPointerDown={handleClosePointerDown}
            type="button"
          >
            <CloseIcon />
          </button>
        </header>
      ) : (
        <button
          aria-label="Close workspace"
          className="workspace-close workspace-single-close"
          onClick={closeWorkspace}
          onPointerDown={handleClosePointerDown}
          type="button"
        >
          <CloseIcon />
        </button>
      )}
      <div className="workspace-panel" role="tabpanel">
        <ResourcePanel
          browserControlsReady={browserControlsReady && !historical}
          conversationId={conversationId}
          historical={historical}
          onBrowserActivate={onBrowserActivate}
          onBrowserResize={onBrowserResize}
          onBrowserScroll={onBrowserScroll}
          onInteraction={onInteraction}
          onCheckAssignment={onCheckAssignment}
          onOpenAssignment={onOpenAssignment}
          onSubmitApplication={onSubmitApplication}
          panel={focused}
        />
      </div>
    </aside>
  );
}
