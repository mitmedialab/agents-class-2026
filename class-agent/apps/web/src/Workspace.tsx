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
  type DraftFieldStatus,
  type PageCardItem,
  type TextHighlightAnchor,
} from "@class-agent/ui";
import type { JsonObject, JsonValue, WorkspacePanel, WorkspaceState } from "@class-agent/workspace";
import { useEffect, useMemo, useState } from "react";

import {
  browserSnapshotUrl,
  browserPreviewSnapshotUrl,
  getCourseResourceContent,
  type CourseResourceContent,
} from "./api.js";

interface WorkspaceProps {
  conversationId: string;
  state: WorkspaceState;
  onPanelAction: (action: "focus" | "close", panelId: string) => Promise<void>;
  onInteraction: (panelId: string, action: string, value: JsonValue) => void;
  onBrowserScroll: (panelId: string, sessionId: string, deltaY: number) => Promise<void>;
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

function stringProp(props: JsonObject, name: string): string | undefined {
  const value = props[name];
  return typeof value === "string" ? value : undefined;
}

function numberProp(props: JsonObject, name: string): number | undefined {
  const value = props[name];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
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
    if (typeof raw.preview_id === "string" && typeof raw.revision === "number") {
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
  conversationId,
  panel,
  onBrowserScroll,
  onBrowserResize,
  onInteraction,
}: {
  conversationId: string;
  panel: WorkspacePanel;
  onBrowserScroll: (panelId: string, sessionId: string, deltaY: number) => Promise<void>;
  onBrowserResize: (
    panelId: string,
    sessionId: string,
    width: number,
    height: number,
  ) => Promise<void>;
  onInteraction: (panelId: string, action: string, value: JsonValue) => void;
}) {
  const [resource, setResource] = useState<CourseResourceContent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const resourceUri = panel.resourceUri ?? DEFAULT_COMPONENT_RESOURCES[panel.componentId];
  const webpageUrl = stringProp(panel.props, "url");
  const webpageMode = stringProp(panel.props, "mode");
  const webpageContent = stringProp(panel.props, "content");
  const draftFields =
    panel.props.fields === undefined ? [] : draftDocumentFields(panel.props.fields);
  const draftContent = stringProp(panel.props, "content");

  useEffect(() => {
    let disposed = false;
    setResource(null);
    setError(null);
    if (
      panel.componentId === "webpage-viewer" ||
      panel.componentId === "browser-viewer" ||
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
    void getCourseResourceContent(resourceUri)
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
      }
    : null;
  const calendarData = useMemo(() => {
    if (!resource) return null;
    try {
      const decoded = new TextDecoder().decode(resource.data);
      return normalizeCalendarData(JSON.parse(decoded) as unknown);
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
    return (
      <BrowserViewer
        imageUrl={browserSnapshotUrl(conversationId, sessionId, revision)}
        onScroll={(deltaY) => onBrowserScroll(panel.id, sessionId, deltaY)}
        onResize={(width, height) =>
          onBrowserResize(panel.id, sessionId, width, height)
        }
        title={title}
        url={url}
        {...(viewportHeight === undefined ? {} : { viewportHeight })}
        {...(viewportWidth === undefined ? {} : { viewportWidth })}
        {...(scrollY === undefined ? {} : { focusScrollY: scrollY })}
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
        items={items}
        onSelect={(id) => onInteraction(panel.id, "page_cards.select", id)}
        {...(description === undefined ? {} : { description })}
        {...(heading === undefined ? {} : { heading })}
        {...(selectedId === undefined ? {} : { selectedId })}
      />
    );
  }
  if (panel.componentId === "visual-composition") {
    const rootId = stringProp(panel.props, "root_id");
    const elements = rootId
      ? normalizeVisualElements(panel.props.elements, rootId)
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
          onInteraction(panel.id, "visual.change", {
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
      <DraftDocument
        description={stringProp(panel.props, "description")}
        content={draftContent}
        fields={draftFields}
        status={
          status === "ready" || status === "final" || status === "submitted"
            ? (status as DraftDocumentStatus)
            : "draft"
        }
        title={stringProp(panel.props, "title") ?? panel.title ?? "Draft document"}
      />
    );
  }
  if (panel.componentId === "draft-document") {
    return <p className="workspace-panel-message">The draft document data is invalid.</p>;
  }
  if (error) return <p className="workspace-panel-message">{error}</p>;
  if (!resource) return <p className="workspace-panel-message">Opening resource…</p>;
  if (panel.componentId === "document-viewer" && documentResource) {
    return (
      <DocumentViewer
        findText={stringProp(panel.props, "find_text")}
        highlight={highlightProp(panel.props.highlight)}
        page={numberProp(panel.props, "page")}
        resource={documentResource}
        onFind={(query) => onInteraction(panel.id, "document.find_text", query)}
        onPageChange={(page) =>
          onInteraction(panel.id, "document.change_page", page)
        }
      />
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
          onInteraction(panel.id, `calendar.${action}`, value)
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
  conversationId,
  state,
  onPanelAction,
  onInteraction,
  onBrowserScroll,
  onBrowserResize,
}: WorkspaceProps) {
  const focused =
    state.panels.find((panel) => panel.id === state.focusedPanelId) ?? state.panels.at(-1);
  if (!focused) return null;
  const tabbed = state.panels.length > 1;

  return (
    <aside
      aria-label="Workspace"
      className="workspace-pane"
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
            aria-label={`Close ${focused.title ?? focused.componentId}`}
            className="workspace-close"
            onClick={() => void onPanelAction("close", focused.id)}
            type="button"
          >
            <span aria-hidden="true">×</span>
          </button>
        </header>
      ) : (
        <button
          aria-label={`Close ${focused.title ?? focused.componentId}`}
          className="workspace-close workspace-single-close"
          onClick={() => void onPanelAction("close", focused.id)}
          type="button"
        >
          <span aria-hidden="true">×</span>
        </button>
      )}
      <div className="workspace-panel" role="tabpanel">
        <ResourcePanel
          conversationId={conversationId}
          onBrowserResize={onBrowserResize}
          onBrowserScroll={onBrowserScroll}
          onInteraction={onInteraction}
          panel={focused}
        />
      </div>
    </aside>
  );
}
