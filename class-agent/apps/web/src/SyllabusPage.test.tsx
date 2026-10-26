import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SyllabusPage } from "./SyllabusPage.js";

const ISSUE = [
  "# High Five, Then Verify",
  "",
  "**Issue:** The Class Runtime · Issue 02",
  "",
  "## Highlights",
  "",
  "### Atlas, Meet Evidence",
  "",
  "01 · Brooke",
  "",
  "[![Atlas, Meet Evidence](agents2026_brooke)](https://example.edu/brooke/week02/)",
  "",
  "![Logo](javascript:alert(1))",
  "",
  "Perci helps you study \\<vision\\> with sources. [Open Brooke's build →](https://example.edu/brooke/week02/)",
  "",
  "## Last word",
  "",
  "> “Offer the thread as a lens.”",
  ">",
  "> — [Egemen, from their week 2 post](https://example.edu/egemen/)",
  "",
  "[All issues →](course://newsletter)",
  "",
  "[Not a page](course://faq)",
].join("\n");

describe("SyllabusPage", () => {
  it("renders figures, quotes, and in-app course links for a newsletter issue", () => {
    const onCourseLink = vi.fn();
    render(
      <SyllabusPage
        content={ISSUE}
        courseLinkPath={(uri) => (uri === "course://newsletter" ? "/newsletter" : null)}
        error={null}
        loading={false}
        onCourseLink={onCourseLink}
        pdfDownloadUrl="/api/v1/course/resources/asset?uri=x&asset_id=pdf"
        pdfLabel="Download issue PDF"
        pdfTitle="The Class Runtime issue"
        resolveImageSource={(source) =>
          /^[a-z0-9_]+$/.test(source) ? `/api/v1/course/resources/asset?asset_id=${source}` : null
        }
      />,
    );

    expect(screen.getByRole("heading", { level: 1, name: "High Five, Then Verify" })).toBeInTheDocument();
    expect(screen.getByText("Issue")).toBeInTheDocument();
    const figure = screen.getByRole("img", { name: "Atlas, Meet Evidence" });
    expect(figure).toHaveAttribute("src", "/api/v1/course/resources/asset?asset_id=agents2026_brooke");
    expect(figure.closest("a")).toHaveAttribute("href", "https://example.edu/brooke/week02/");
    expect(figure.closest("figure")).toHaveClass("syllabus-figure");
    // An image whose source is neither an asset id nor https is dropped, not rendered.
    expect(screen.queryByRole("img", { name: "Logo" })).not.toBeInTheDocument();
    expect(screen.getByText(/Perci helps you study <vision> with sources\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Brooke's build →" })).toHaveAttribute(
      "target",
      "_blank",
    );
    const quote = screen.getByText("“Offer the thread as a lens.”").closest("blockquote");
    expect(quote).not.toBeNull();
    expect(screen.getByRole("link", { name: "Egemen, from their week 2 post" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download issue PDF" })).toHaveAttribute(
      "download",
      "The Class Runtime issue.pdf",
    );

    const allIssues = screen.getByRole("link", { name: "All issues →" });
    expect(allIssues).toHaveAttribute("href", "/newsletter");
    expect(allIssues).not.toHaveAttribute("target");
    fireEvent.click(allIssues);
    expect(onCourseLink).toHaveBeenCalledWith("course://newsletter");
    // A course:// link without a page is shown as text, never as a dead link.
    expect(screen.queryByRole("link", { name: "Not a page" })).not.toBeInTheDocument();
    expect(screen.getByText("Not a page")).toBeInTheDocument();
  });

  it("shows a wordmark before the title as the masthead, and labelled lines as facts", () => {
    const list = [
      "![The Class Runtime](logo)",
      "",
      "# The Class Runtime",
      "",
      "**What it is:** The weekly newsletter.",
      "",
      "## [Issue 01 · Loop, There It Is](course://newsletter/2026-week01)",
      "",
      "**Week:** Week 1 · Sep 15 – Sep 21, 2026",
      "**Sent:** Sep 28, 2026",
      "**Featured:** Mateo and Leticia",
      "",
      "Plain paragraph after the facts.",
    ].join("\n");
    render(
      <SyllabusPage
        content={list}
        courseLinkPath={() => "/newsletter/2026-week01"}
        error={null}
        loading={false}
        resolveImageSource={(source) => `/asset/${source}`}
      />,
    );
    const masthead = screen.getByRole("img", { name: "The Class Runtime" });
    expect(masthead).toHaveAttribute("src", "/asset/logo");
    expect(masthead.closest(".syllabus-masthead")).not.toBeNull();
    // The wordmark names the page, so the heading stays only for assistive technology.
    expect(screen.getByRole("heading", { level: 1, name: "The Class Runtime" })).toHaveClass(
      "ca-visually-hidden",
    );
    expect(screen.getByText("What it is")).toBeInTheDocument();
    const facts = screen.getByText("Week").closest("dl");
    expect(facts).toHaveClass("syllabus-facts");
    expect(facts?.querySelectorAll("dt")).toHaveLength(3);
    expect(screen.getByText("Mateo and Leticia").tagName).toBe("DD");
    expect(screen.getByText("Plain paragraph after the facts.").tagName).toBe("P");
    expect(screen.getByRole("link", { name: "Issue 01 · Loop, There It Is" })).toHaveAttribute(
      "href",
      "/newsletter/2026-week01",
    );
  });

  it("draws rules, links fact labels, and takes a reading layout", () => {
    const content = [
      "# Issue",
      "",
      "## All the builds this week",
      "",
      "**[Grace](https://g.example/):** Grace built a loop.",
      "**Ivy:** Nothing posted for this week yet.",
      "",
      "---",
      "",
      "This newsletter was created by The Course Agent.",
    ].join("\n");
    const { container } = render(
      <SyllabusPage content={content} error={null} layout="reading" loading={false} />,
    );
    expect(container.querySelector("article")).toHaveAttribute("data-layout", "reading");
    const grace = screen.getByRole("link", { name: "Grace" });
    expect(grace.closest("dt")).not.toBeNull();
    expect(screen.getByText("Grace built a loop.").tagName).toBe("DD");
    expect(screen.getByText("Ivy").tagName).toBe("DT");
    expect(container.querySelectorAll("hr")).toHaveLength(1);
    expect(screen.getByText("This newsletter was created by The Course Agent.").tagName).toBe("P");
  });

  it("keeps the title visible when the masthead does not name the page", () => {
    render(
      <SyllabusPage
        content={"![The Class Runtime](logo)\n\n# High Five, Then Verify\n\nBody."}
        error={null}
        loading={false}
        resolveImageSource={(source) => `/asset/${source}`}
      />,
    );
    expect(screen.getByRole("img", { name: "The Class Runtime" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "High Five, Then Verify" })).not.toHaveClass(
      "ca-visually-hidden",
    );
  });

  it("renders no images when the page has no image resolver", () => {
    render(<SyllabusPage content={ISSUE} error={null} loading={false} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Atlas, Meet Evidence" })).toBeInTheDocument();
  });
});
