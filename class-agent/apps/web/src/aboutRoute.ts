import { useCallback, useEffect, useState } from "react";

/** Course documents shown in place of the chat, each at its own shareable path. */
export type CourseDocument =
  | "syllabus"
  | "newsletter-highlights"
  | "newsletter"
  | "newsletter-issue";

export interface CourseDocumentRoute {
  errorMessage: string;
  /** Wide reference column (tables), or a reading measure for long prose. */
  layout: "reference" | "reading";
  loadingMessage: string;
  /** The download control, shown when the resource advertises a registered PDF. */
  pdfLabel: string;
  pdfTitle: string;
}

/** One open document: its kind, the registered resource behind it, and its path. */
export interface CourseDocumentLocation {
  document: CourseDocument;
  path: string;
  uri: string;
}

export const COURSE_DOCUMENTS: Record<CourseDocument, CourseDocumentRoute> = {
  syllabus: {
    errorMessage: "The syllabus could not be loaded. Please try again.",
    layout: "reference",
    loadingMessage: "Loading syllabus…",
    pdfLabel: "Download syllabus PDF",
    pdfTitle: "Course syllabus",
  },
  // How The Class Runtime picks highlights; issues now link to the Course Agent's FAQ answer.
  "newsletter-highlights": {
    errorMessage: "This page could not be loaded. Please try again.",
    layout: "reference",
    loadingMessage: "Loading…",
    pdfLabel: "Download PDF",
    pdfTitle: "How The Class Runtime chooses its highlights",
  },
  // Every sent issue of the weekly newsletter, newest first.
  newsletter: {
    errorMessage: "The newsletters could not be loaded. Please try again.",
    layout: "reading",
    loadingMessage: "Loading newsletters…",
    pdfLabel: "Download PDF",
    pdfTitle: "The Class Runtime",
  },
  // One sent issue, with its highlight images and every link active.
  "newsletter-issue": {
    errorMessage: "This issue could not be loaded. Please try again.",
    layout: "reading",
    loadingMessage: "Loading issue…",
    pdfLabel: "Download issue PDF",
    pdfTitle: "The Class Runtime issue",
  },
};

type FixedDocument = Exclude<CourseDocument, "newsletter-issue">;

const FIXED_DOCUMENTS: Record<FixedDocument, CourseDocumentLocation> = {
  syllabus: { document: "syllabus", path: "/about", uri: "course://syllabus" },
  "newsletter-highlights": {
    document: "newsletter-highlights",
    path: "/newsletter/highlights",
    uri: "course://newsletter-highlights",
  },
  newsletter: { document: "newsletter", path: "/newsletter", uri: "course://newsletter" },
};

// A sent issue lives at /newsletter/<year>-week<NN>, the path form of its resource URI.
const NEWSLETTER_ISSUE_ID = /^[0-9]{4}-week[0-9]{2}$/;
const NEWSLETTER_ISSUE_PATH_PREFIX = "/newsletter/";
const NEWSLETTER_ISSUE_URI_PREFIX = "course://newsletter/";

export function fixedDocument(document: FixedDocument): CourseDocumentLocation {
  return FIXED_DOCUMENTS[document];
}

function newsletterIssue(issueId: string): CourseDocumentLocation | null {
  return NEWSLETTER_ISSUE_ID.test(issueId)
    ? {
        document: "newsletter-issue",
        path: `${NEWSLETTER_ISSUE_PATH_PREFIX}${issueId}`,
        uri: `${NEWSLETTER_ISSUE_URI_PREFIX}${issueId}`,
      }
    : null;
}

export function documentForPath(pathname: string): CourseDocumentLocation | null {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  const fixed = Object.values(FIXED_DOCUMENTS).find((location) => location.path === normalized);
  if (fixed) return fixed;
  return normalized.startsWith(NEWSLETTER_ISSUE_PATH_PREFIX)
    ? newsletterIssue(normalized.slice(NEWSLETTER_ISSUE_PATH_PREFIX.length))
    : null;
}

/** The page for a `course://` link inside a document, when that resource has one. */
export function documentForUri(uri: string): CourseDocumentLocation | null {
  const fixed = Object.values(FIXED_DOCUMENTS).find((location) => location.uri === uri);
  if (fixed) return fixed;
  return uri.startsWith(NEWSLETTER_ISSUE_URI_PREFIX)
    ? newsletterIssue(uri.slice(NEWSLETTER_ISSUE_URI_PREFIX.length))
    : null;
}

export function urlForAboutState(
  href: string,
  open: boolean,
  location: CourseDocumentLocation = FIXED_DOCUMENTS.syllabus,
): string {
  const url = new URL(href);
  if (open) {
    url.pathname = location.path;
  } else if (documentForPath(url.pathname) !== null) {
    url.pathname = "/";
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * Whether a course document is open, a navigator, and which document it is. Opening without a
 * location means the syllabus, which is what the About button shows.
 */
export function useAboutRoute(): [
  boolean,
  (open: boolean, location?: CourseDocumentLocation) => void,
  CourseDocumentLocation,
] {
  const [current, setCurrent] = useState<CourseDocumentLocation | null>(() =>
    documentForPath(window.location.pathname),
  );

  useEffect(() => {
    const handlePopState = () => setCurrent(documentForPath(window.location.pathname));
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = useCallback(
    (nextOpen: boolean, nextLocation: CourseDocumentLocation = FIXED_DOCUMENTS.syllabus) => {
      const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      const nextUrl = urlForAboutState(window.location.href, nextOpen, nextLocation);
      if (nextUrl !== currentUrl) {
        window.history.pushState(window.history.state, "", nextUrl);
      }
      setCurrent(nextOpen ? nextLocation : null);
    },
    [],
  );

  return [current !== null, navigate, current ?? FIXED_DOCUMENTS.syllabus];
}
