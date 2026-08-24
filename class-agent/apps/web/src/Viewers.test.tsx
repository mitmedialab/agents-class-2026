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
  resolveTextAnchor,
} from "@class-agent/ui";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

describe("DocumentViewer", () => {
  it("resolves a semantic quote with surrounding text and highlights Markdown", () => {
    const content =
      "# Syllabus\n\nPresentation week. Final projects are due at 11:59 PM.\n";
    const anchor = {
      resourceUri: "course://syllabus",
      page: 1,
      quote: "Final projects are due",
      prefix: "Presentation week.",
      suffix: "at 11:59 PM.",
    };
    expect(resolveTextAnchor(content, anchor)).toEqual({ start: 31, end: 53 });

    render(
      <DocumentViewer
        highlight={anchor}
        resource={{
          uri: "course://syllabus",
          title: "Syllabus",
          mediaType: "text/markdown",
          data: new TextEncoder().encode(content),
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "Syllabus" })).toBeInTheDocument();
    expect(screen.getByText("Final projects are due", { selector: "mark" })).toBeInTheDocument();
  });

  it("finds text and exposes match navigation", () => {
    const onFind = vi.fn();
    render(
      <DocumentViewer
        onFind={onFind}
        resource={{
          uri: "course://notes",
          title: "Notes",
          mediaType: "text/plain",
          data: new TextEncoder().encode("agent one\nagent two"),
        }}
      />,
    );
    fireEvent.change(screen.getByRole("searchbox", { name: "Find in document" }), {
      target: { value: "agent" },
    });
    fireEvent.submit(screen.getByRole("searchbox", { name: "Find in document" }).closest("form")!);
    expect(onFind).toHaveBeenCalledWith("agent");
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
  });
});

describe("Calendar", () => {
  it("normalizes the course schedule without inventing missing dates", () => {
    const data = normalizeCalendarData({
      status: "provisional",
      weeks: [
        {
          week: 1,
          date_label: "9/20",
          lecture: "Introduction",
          speakers: ["Pattie Maes"],
          tutorial: "Build a minimal agent.",
          readings: "ReAct",
        },
        { week: 2, date_label: null, lecture: "Tools" },
      ],
    });
    expect(data.events).toEqual([
      {
        id: "week-1",
        title: "Introduction",
        week: 1,
        type: "class",
        dateLabel: "9/20",
        speakers: ["Pattie Maes"],
        activity: "Build a minimal agent.",
        readings: "ReAct",
      },
      { id: "week-2", title: "Tools", week: 2, type: "class" },
    ]);

    render(<Calendar data={data} view="agenda" />);
    expect(screen.getByText("Introduction")).toBeInTheDocument();
    expect(screen.getByText("Date TBA")).toBeInTheDocument();
    expect(screen.getByText("Week 1")).toBeInTheDocument();
    expect(screen.getByText("Speaker: Pattie Maes")).toBeInTheDocument();
    expect(screen.getByText("Build a minimal agent.")).toBeInTheDocument();
    expect(screen.queryByText("ReAct")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Introduction/ }));
    expect(screen.getByRole("region", { name: "Readings for Introduction" })).toHaveTextContent(
      "ReAct",
    );
    fireEvent.click(screen.getByRole("button", { name: "Month" }));
    expect(screen.getByRole("grid", { name: "Month" })).toBeInTheDocument();
    expect(
      screen.getByText("Events without confirmed dates are listed in Agenda view."),
    ).toBeInTheDocument();
  });
});

describe("WebpageViewer", () => {
  it("opens HTTPS pages in an isolated iframe with an external fallback", () => {
    render(
      <WebpageViewer mode="live" title="MIT Media Lab" url="https://www.media.mit.edu/" />,
    );

    const frame = screen.getByTitle("MIT Media Lab");
    expect(frame).toHaveAttribute("src", "https://www.media.mit.edu/");
    expect(frame).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(frame.getAttribute("sandbox")).toContain("allow-scripts");
    expect(frame.getAttribute("sandbox")).not.toContain("allow-same-origin");
    expect(screen.getByRole("link", { name: "Open externally" })).toHaveAttribute(
      "href",
      "https://www.media.mit.edu/",
    );
    expect(
      screen.getByText("This site controls whether live embedding is allowed."),
    ).toBeInTheDocument();
  });

  it("renders agent-read content as a safe reader snapshot without an iframe", () => {
    render(
      <WebpageViewer
        content={"# Media Lab\n\nResearch across disciplines."}
        title="MIT Media Lab"
        url="https://www.media.mit.edu/"
      />,
    );

    expect(screen.queryByTitle("MIT Media Lab")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Media Lab" })).toBeInTheDocument();
    expect(screen.getByText("Research across disciplines.")).toBeInTheDocument();
    expect(screen.getByText(/Reader snapshot/)).toBeInTheDocument();
  });

  it("shows a clean fallback instead of attempting a legacy URL-only iframe", () => {
    render(<WebpageViewer title="Google" url="https://www.google.com/" />);

    expect(screen.queryByTitle("Google")).not.toBeInTheDocument();
    expect(screen.getByText("Reader snapshot unavailable")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open page" })).toHaveAttribute(
      "href",
      "https://www.google.com/",
    );
  });

  it("rejects non-HTTPS and credential-bearing URLs", () => {
    const { rerender } = render(<WebpageViewer url="http://example.com" />);
    expect(screen.queryByTitle("Web page")).not.toBeInTheDocument();
    expect(screen.getByText("This component can only open secure HTTPS pages.")).toBeInTheDocument();

    rerender(<WebpageViewer url="https://user:secret@example.com" />);
    expect(screen.queryByTitle("Web page")).not.toBeInTheDocument();
  });
});

describe("BrowserViewer", () => {
  it("renders a full-width server snapshot and scrolls locally from its controls", () => {
    const onScroll = vi.fn();
    const scrollBy = vi.fn();
    render(
      <BrowserViewer
        imageUrl="/api/v1/browser/session/snapshot?revision=2"
        onScroll={onScroll}
        title="MIT Media Lab"
        url="https://www.media.mit.edu/"
      />,
    );

    expect(screen.getByAltText("Remote browser showing MIT Media Lab")).toHaveAttribute(
      "src",
      "/api/v1/browser/session/snapshot?revision=2",
    );
    expect(screen.getByText("Isolated read-only session · content is rendered on the Course Agent server"))
      .toBeInTheDocument();
    const viewport = screen.getByRole("region", {
      name: "Scrollable remote browser image",
    });
    Object.defineProperty(viewport, "scrollBy", { value: scrollBy });
    fireEvent.click(screen.getByRole("button", { name: "Scroll page down" }));
    expect(scrollBy).toHaveBeenCalledWith({ top: 640, behavior: "smooth" });
    expect(onScroll).not.toHaveBeenCalled();
  });

  it("leaves mouse-wheel input local instead of issuing remote frame requests", () => {
    const onScroll = vi.fn();
    render(
      <BrowserViewer
        imageUrl="/snapshot.png"
        onScroll={onScroll}
        title="Example"
        url="https://example.com/"
      />,
    );

    fireEvent.wheel(screen.getByRole("region", { name: "Scrollable remote browser image" }), {
      deltaY: 320,
    });
    expect(onScroll).not.toHaveBeenCalled();
  });

  it("uses the remote scroll callback only to recover an unavailable session", () => {
    const onScroll = vi.fn();
    render(
      <BrowserViewer
        imageUrl="/expired.png"
        onScroll={onScroll}
        title="Example"
        url="https://example.com/"
      />,
    );

    fireEvent.error(screen.getByAltText("Remote browser showing Example"));
    fireEvent.click(screen.getByRole("button", { name: "Scroll page down" }));
    expect(onScroll).toHaveBeenCalledWith(640);
  });
});

describe("PageCards", () => {
  it("renders adjacent preview candidates and records selection", () => {
    const onSelect = vi.fn();
    render(
      <PageCards
        heading="Project candidates"
        items={[
          {
            id: "first",
            title: "First project",
            url: "https://example.com/first",
            imageUrl: "/preview/first.png",
          },
          {
            id: "second",
            title: "Second project",
            url: "https://example.com/second",
            imageUrl: "/preview/second.png",
          },
        ]}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByText("2 candidates")).toBeInTheDocument();
    expect(screen.getByAltText("Preview of First project")).toHaveAttribute(
      "src",
      "/preview/first.png",
    );
    fireEvent.click(screen.getByRole("button", { name: /Second project/ }));
    expect(onSelect).toHaveBeenCalledWith("second");
    expect(screen.getByRole("button", { name: /Second project/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("falls back to a safe external link if a preview expires", () => {
    render(
      <PageCards
        items={[
          { id: "one", title: "One", url: "https://example.com/one" },
          { id: "two", title: "Two", url: "https://example.com/two" },
        ]}
      />,
    );

    expect(screen.getAllByText("Preview unavailable")).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "Open page" })[0]).toHaveAttribute(
      "href",
      "https://example.com/one",
    );
  });
});

describe("VisualComposition", () => {
  const elements = [
    {
      id: "profile",
      type: "group" as const,
      children: ["photo", "details"],
      layout: "row" as const,
      surface: "raised" as const,
      padding: "large" as const,
    },
    {
      id: "photo",
      type: "image" as const,
      url: "https://example.com/photo.jpg",
      alt: "Ada Example",
      radius: "round" as const,
      width: "third" as const,
    },
    {
      id: "details",
      type: "group" as const,
      children: ["name", "role", "bio"],
    },
    { id: "name", type: "heading" as const, text: "Ada Example", size: "large" as const },
    { id: "role", type: "badge" as const, label: "Instructor", tone: "accent" as const },
    {
      id: "bio",
      type: "textarea" as const,
      label: "Bio",
      value: "Builds cognitive interfaces.",
    },
  ];

  it("composes a profile from reusable visual elements", () => {
    const onChange = vi.fn();
    render(
      <VisualComposition
        elements={elements}
        onChange={onChange}
        rootId="profile"
        title="Instructor profile"
      />,
    );

    expect(screen.getByRole("heading", { name: "Ada Example" })).toBeInTheDocument();
    expect(screen.getByAltText("Ada Example")).toHaveAttribute(
      "referrerpolicy",
      "no-referrer",
    );
    expect(screen.getByText("Instructor")).toBeInTheDocument();
    const bio = screen.getByRole("textbox", { name: "Bio" });
    fireEvent.change(bio, { target: { value: "Updated biography." } });
    fireEvent.blur(bio);
    expect(onChange).toHaveBeenCalledWith("bio", "Updated biography.");
  });

  it("rejects cycles, shared children, and unreachable visual objects", () => {
    expect(normalizeVisualElements(elements, "profile")).not.toBeNull();
    expect(
      normalizeVisualElements(
        [
          { id: "first", type: "group", children: ["second"] },
          { id: "second", type: "group", children: ["first"] },
        ],
        "first",
      ),
    ).toBeNull();
    expect(
      normalizeVisualElements(
        [
          { id: "root", type: "text", text: "Visible" },
          { id: "orphan", type: "text", text: "Hidden" },
        ],
        "root",
      ),
    ).toBeNull();
  });
});

describe("DraftDocument", () => {
  it("renders progressive field values and distinguishes confirmation state", () => {
    render(
      <DraftDocument
        fields={[
          { id: "name", label: "Name", value: "Ada Example", status: "confirmed" },
          { id: "interests", label: "Interests", status: "missing" },
          {
            id: "skills",
            label: "Skills",
            value: "Creative coding",
            status: "inferred",
            source: "Portfolio",
          },
        ]}
        title="Course application"
      />,
    );

    expect(screen.getByLabelText("2 of 3 fields populated")).toBeInTheDocument();
    expect(screen.getByText("Ada Example")).toBeInTheDocument();
    expect(screen.getByText("Waiting for information")).toBeInTheDocument();
    expect(screen.getByText("Inferred")).toBeInTheDocument();
    expect(screen.getByText("Source: Portfolio")).toBeInTheDocument();
  });

  it("renders a general prose draft without requiring form fields", () => {
    render(
      <DraftDocument
        content={"# Overview\n\nA situated agent for collaborative learning."}
        status="ready"
        title="Project proposal"
      />,
    );

    expect(screen.getByRole("heading", { name: "Project proposal" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByText("A situated agent for collaborative learning.")).toBeInTheDocument();
    expect(screen.queryByText("Waiting for information")).not.toBeInTheDocument();
  });
});
