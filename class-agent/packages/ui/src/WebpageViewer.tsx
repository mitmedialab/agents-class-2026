import { DocumentViewer } from "./DocumentViewer.js";

export interface WebpageViewerProps {
  url: string;
  title?: string | undefined;
  mode?: "reader" | "live" | undefined;
  content?: string | undefined;
}

function secureUrl(value: string): URL | null {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function WebpageViewer({
  url,
  title = "Web page",
  mode = "reader",
  content,
}: WebpageViewerProps) {
  const parsed = secureUrl(url);
  if (!parsed) {
    return (
      <section aria-label={title} className="ca-webpage-viewer ca-webpage-error">
        <p>This component can only open secure HTTPS pages.</p>
      </section>
    );
  }

  return (
    <section aria-label={title} className="ca-webpage-viewer">
      <header className="ca-webpage-toolbar">
        <div>
          <strong>{title}</strong>
          <span>
            {parsed.hostname} · {mode === "live" ? "Live embed" : "Reader snapshot"}
          </span>
        </div>
        <a href={parsed.href} rel="noreferrer" target="_blank">
          Open externally
        </a>
      </header>
      {mode === "live" ? (
        <>
          <p className="ca-webpage-live-notice">
            This site controls whether live embedding is allowed.
          </p>
          <iframe
            loading="eager"
            referrerPolicy="no-referrer"
            sandbox="allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-scripts"
            src={parsed.href}
            title={title}
          />
        </>
      ) : content?.trim() ? (
        <div className="ca-webpage-reader">
          <DocumentViewer
            resource={{
              uri: parsed.href,
              title,
              mediaType: "text/markdown",
              data: new TextEncoder().encode(content),
            }}
          />
        </div>
      ) : (
        <div className="ca-webpage-fallback">
          <strong>Reader snapshot unavailable</strong>
          <p>This page was not embedded because the site may block iframes.</p>
          <a href={parsed.href} rel="noreferrer" target="_blank">
            Open page
          </a>
        </div>
      )}
    </section>
  );
}
