import { describe, expect, it } from "vitest";

import {
  COURSE_DOCUMENTS,
  documentForPath,
  documentForUri,
  fixedDocument,
  urlForAboutState,
} from "./aboutRoute.js";

describe("course document routes", () => {
  it("maps each document path, with or without a trailing slash", () => {
    expect(documentForPath("/about")?.document).toBe("syllabus");
    expect(documentForPath("/about/")?.document).toBe("syllabus");
    expect(documentForPath("/newsletter/highlights")).toEqual({
      document: "newsletter-highlights",
      path: "/newsletter/highlights",
      uri: "course://newsletter-highlights",
    });
    expect(documentForPath("/newsletter/highlights/")?.document).toBe("newsletter-highlights");
    expect(documentForPath("/newsletter")).toEqual(fixedDocument("newsletter"));
    expect(documentForPath("/newsletter/")?.uri).toBe("course://newsletter");
    expect(documentForPath("/")).toBeNull();
    expect(COURSE_DOCUMENTS.newsletter.loadingMessage).toBe("Loading newsletters…");
  });

  it("maps a sent issue between its path and its resource, and nothing else", () => {
    const issue = {
      document: "newsletter-issue",
      path: "/newsletter/2026-week02",
      uri: "course://newsletter/2026-week02",
    };
    expect(documentForPath("/newsletter/2026-week02")).toEqual(issue);
    expect(documentForPath("/newsletter/2026-week02/")).toEqual(issue);
    expect(documentForUri("course://newsletter/2026-week02")).toEqual(issue);
    expect(documentForUri("course://newsletter")).toEqual(fixedDocument("newsletter"));
    expect(documentForUri("course://syllabus")).toEqual(fixedDocument("syllabus"));
    // Only the issue-id form is a page; other names under the prefix are not routed.
    expect(documentForPath("/newsletter/2026-week2")).toBeNull();
    expect(documentForPath("/newsletter/issues/2026-week02")).toBeNull();
    expect(documentForUri("course://newsletter/../syllabus")).toBeNull();
    expect(documentForUri("course://faq")).toBeNull();
    expect(COURSE_DOCUMENTS["newsletter-issue"].pdfLabel).toBe("Download issue PDF");
  });

  it("opens a document at its path and closes any document back to the chat", () => {
    const base = "https://cognitive-agents.media.mit.edu";
    expect(urlForAboutState(`${base}/?q=1#top`, true)).toBe("/about?q=1#top");
    expect(urlForAboutState(`${base}/`, true, fixedDocument("newsletter-highlights"))).toBe(
      "/newsletter/highlights",
    );
    expect(urlForAboutState(`${base}/`, true, fixedDocument("newsletter"))).toBe("/newsletter");
    expect(
      urlForAboutState(`${base}/newsletter`, true, documentForUri("course://newsletter/2026-week02")!),
    ).toBe("/newsletter/2026-week02");
    expect(urlForAboutState(`${base}/newsletter/2026-week02`, false)).toBe("/");
    expect(urlForAboutState(`${base}/newsletter/highlights`, false)).toBe("/");
    expect(urlForAboutState(`${base}/about`, false)).toBe("/");
  });
});
