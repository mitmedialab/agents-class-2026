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
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import publishedSchedule from "../../../shared/course/schedule/schedule.md?raw";

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
  it("parses every row in the published schedule source", () => {
    const data = normalizeCalendarData(publishedSchedule);

    expect(data.year).toBe(2026);
    expect(data.events).toHaveLength(14);
    expect(data.events[0]).toMatchObject({
      week: 1,
      dateLabel: "9/15",
      title: "Course introduction: What is an AI agent?",
      speakers: ["Prof. Pattie Maes", "Valdemar Danry"],
      tutorialSpeakers: ["Wazeer Zulfikar"],
    });
    expect(data.events[6]).toMatchObject({
      week: 7,
      tutorialSpeakers: ["Wazeer Zulfikar", "Yasith Samaradivakara"],
    });
    expect(data.events.at(-1)).toMatchObject({
      week: 14,
      dateLabel: "TBD",
      title: "Final project presentations",
    });
    expect(data.notices).toContainEqual({
      label: "Application deadline",
      text: "September 5, midnight",
    });
    expect(data.notices).toContainEqual({
      label: "Acceptance notification",
      text: "September 9, midnight",
    });

    render(<Calendar data={data} focusDate="2025-09-15" view="month" />);
    expect(screen.getByRole("heading", { name: "September 2026" })).toBeInTheDocument();
    expect(
      screen.getByRole("gridcell", { name: "Tuesday, September 1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Course introduction: What is an AI agent?" }),
    ).toBeInTheDocument();
  });

  it("parses the editable Markdown schedule into complete calendar events", () => {
    const data = normalizeCalendarData(`# Fall 2026 Schedule

**Notes: Every lecture begins with a 15 minute show and tell.**
**Application deadline: September 5, midnight**
**Acceptance notification: September 9, midnight**

| Date / Week | Lecture Topics (45 min) | Hands-on tutorial (50 min) | Suggested Readings |
| --- | --- | --- | --- |
| Week 1 (9/15) | **Course introduction: What is an AI agent?** The history of AI agents. *Prof. Pattie Maes & Valdemar Danry* | Build a minimal agent loop. *Wazeer Zulfikar* | ReAct; [MCP](https://modelcontextprotocol.io/specification) |
| Week 5 (10/13) | No class | No class | No class |
| Week 14 TBD | **Final project presentations** Live demo \\+ failure analysis | Final demos | Final project reports |
`);

    expect(data.notices).toEqual([
      { label: "Notes", text: "Every lecture begins with a 15 minute show and tell." },
      { label: "Application deadline", text: "September 5, midnight" },
      { label: "Acceptance notification", text: "September 9, midnight" },
    ]);
    expect(data.year).toBe(2026);
    expect(data.events).toEqual([
      {
        id: "week-1",
        week: 1,
        type: "class",
        title: "Course introduction: What is an AI agent?",
        description: "The history of AI agents.",
        speakers: ["Prof. Pattie Maes", "Valdemar Danry"],
        dateLabel: "9/15",
        activity: "Build a minimal agent loop.",
        tutorialSpeakers: ["Wazeer Zulfikar"],
        readings: "ReAct; MCP (https://modelcontextprotocol.io/specification)",
      },
      {
        id: "week-5",
        week: 5,
        type: "no-class",
        title: "No class",
        dateLabel: "10/13",
      },
      {
        id: "week-14",
        week: 14,
        type: "class",
        title: "Final project presentations",
        description: "Live demo + failure analysis",
        dateLabel: "TBD",
        activity: "Final demos",
        readings: "Final project reports",
      },
    ]);

    render(<Calendar data={data} focusDate="2026-09-20" view="agenda" />);
    expect(screen.getByRole("complementary", { name: "Schedule notices" })).toHaveTextContent(
      "Application deadlineSeptember 5, midnight",
    );
    expect(screen.getByText("The history of AI agents.")).toBeInTheDocument();
    expect(screen.getByText("Tutorial lead: Wazeer Zulfikar")).toBeInTheDocument();
  });

  it("normalizes the course schedule without inventing missing dates", () => {
    const data = normalizeCalendarData({
      status: "provisional",
      year: 2026,
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
    expect(screen.getByText("ReAct")).toBeInTheDocument();
    expect(screen.getByText("Suggested readings")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suggested readings" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Month" }));
    expect(screen.getByRole("grid", { name: "Month" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Introduction" })).toBeInTheDocument();
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
    expect(screen.getByText(/click links and controls directly/))
      .toBeInTheDocument();
    const viewport = screen.getByRole("region", {
      name: "Scrollable remote browser image",
    });
    Object.defineProperty(viewport, "scrollBy", { value: scrollBy });
    fireEvent.click(screen.getByRole("button", { name: "Scroll page down" }));
    expect(scrollBy).toHaveBeenCalledWith({ top: 640, behavior: "smooth" });
    expect(onScroll).not.toHaveBeenCalled();
  });

  it("maps a snapshot click into remote document coordinates", async () => {
    const onActivate = vi.fn().mockResolvedValue(undefined);
    render(
      <BrowserViewer
        imageUrl="/snapshot.png"
        onActivate={onActivate}
        title="Example"
        url="https://example.com/"
      />,
    );
    const image = screen.getByAltText("Remote browser showing Example");
    Object.defineProperty(image, "naturalWidth", { value: 1280 });
    Object.defineProperty(image, "naturalHeight", { value: 1600 });
    vi.spyOn(image, "getBoundingClientRect").mockReturnValue({
      bottom: 270,
      height: 250,
      left: 10,
      right: 510,
      top: 20,
      width: 500,
      x: 10,
      y: 20,
      toJSON: () => ({}),
    });
    fireEvent.load(image);
    fireEvent.click(image, { clientX: 260, clientY: 145 });

    await waitFor(() => expect(onActivate).toHaveBeenCalledWith(640, 800));
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
      presentation: "avatar" as const,
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
    expect(document.querySelector('[data-element-id="profile"]')).toHaveAttribute(
      "data-root",
      "true",
    );
    expect(screen.getByAltText("Ada Example")).toHaveAttribute(
      "referrerpolicy",
      "no-referrer",
    );
    expect(screen.getByAltText("Ada Example").closest("figure")).toHaveAttribute(
      "data-presentation",
      "avatar",
    );
    expect(screen.getByText("Instructor")).toBeInTheDocument();
    const bio = screen.getByRole("textbox", { name: "Bio" });
    fireEvent.change(bio, { target: { value: "Updated biography." } });
    fireEvent.blur(bio);
    expect(onChange).toHaveBeenCalledWith("bio", "Updated biography.");
  });

  it("gives minimally specified root layouts polished spacing defaults", () => {
    render(
      <VisualComposition
        elements={[
          {
            id: "overview",
            type: "group",
            children: ["heading"],
          },
          { id: "heading", type: "heading", text: "Overview" },
        ]}
        rootId="overview"
      />,
    );

    const root = document.querySelector('[data-element-id="overview"]');
    expect(root).toHaveAttribute("data-root", "true");
    expect(root).toHaveAttribute("data-padding", "large");
    expect(root).toHaveAttribute("data-gap", "loose");
  });

  it("preserves searched image dimensions for uncropped visual layouts", () => {
    render(
      <VisualComposition
        elements={[
          {
            id: "figure",
            type: "image",
            url: "https://example.com/wide-study-figure.png",
            alt: "Study procedure",
            source_width: 2400,
            source_height: 600,
            presentation: "feature",
            fit: "contain",
          },
        ]}
        rootId="figure"
      />,
    );

    const image = screen.getByAltText("Study procedure");
    expect(image).toHaveAttribute("width", "2400");
    expect(image).toHaveAttribute("height", "600");
    expect(image.closest("figure")).toHaveAttribute("data-source-dimensions", "known");
    expect(
      normalizeVisualElements(
        [
          {
            id: "invalid",
            type: "image",
            url: "https://example.com/image.png",
            alt: "Invalid dimensions",
            source_width: 1200,
          },
        ],
        "invalid",
      ),
    ).toBeNull();
  });

  it("renders accessible bar and line charts from declarative data", () => {
    const chartElements = [
      {
        id: "results",
        type: "group" as const,
        layout: "grid" as const,
        children: ["comparison", "trend"],
      },
      {
        id: "comparison",
        type: "chart" as const,
        title: "Section comparison",
        chart_type: "bar" as const,
        labels: ["Section A", "Section B"],
        series: [
          {
            label: "Average score",
            values: [72, 84],
            tones: ["coral" as const, "violet" as const],
          },
        ],
        comparison_basis: "Both sections use the same 0–100 score scale.",
        data_kind: "measured" as const,
        data_source: "Course records, 2026",
        unit: "percent",
        value_suffix: "%",
      },
      {
        id: "trend",
        type: "chart" as const,
        title: "Weekly participation",
        chart_type: "line" as const,
        labels: ["Week 1", "Week 2", "Week 3"],
        series: [
          { label: "Attended", values: [18, 22, 25], tone: "success" as const },
          { label: "Submitted", values: [15, 19, 24], tone: "secondary" as const },
        ],
        comparison_basis: "Each series counts students per course week.",
        data_kind: "measured" as const,
        data_source: "Weekly attendance records",
        unit: "students",
      },
    ];

    expect(normalizeVisualElements(chartElements, "results")).not.toBeNull();
    const { container } = render(
      <VisualComposition elements={chartElements} rootId="results" />,
    );

    expect(screen.getByRole("img", { name: "Section comparison" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Weekly participation" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Section comparison" })).toHaveTextContent(
      "84%",
    );
    expect(screen.getByRole("list", { name: "Chart legend" })).toHaveTextContent(
      "Submitted",
    );
    expect(screen.getByText("Source · Course records, 2026")).toBeInTheDocument();
    const bars = container.querySelectorAll(".ca-chart-bars > g");
    expect(bars[0]).toHaveAttribute("data-tone", "coral");
    expect(bars[1]).toHaveAttribute("data-tone", "violet");
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
    expect(
      normalizeVisualElements(
        [
          {
            id: "invalid-chart",
            type: "chart",
            title: "Invalid",
            chart_type: "bar",
            labels: ["A", "B"],
            series: [{ label: "Value", values: [1] }],
          },
        ],
        "invalid-chart",
      ),
    ).toBeNull();
  });
});

describe("DraftDocument", () => {
  it("renders confirmed fields plus the next unresolved field", () => {
    render(
      <DraftDocument
        fields={[
          { id: "name", label: "Name", value: "Ada Example", status: "confirmed" },
          {
            id: "skills",
            label: "Skills",
            value: "Creative coding",
            status: "inferred",
            source: "Portfolio",
          },
          { id: "interests", label: "Interests", status: "missing" },
        ]}
        title="Course application"
      />,
    );

    expect(screen.getByLabelText("2 of 3 fields populated")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("Ada Example");
    expect(screen.getByRole("textbox", { name: "Skills" })).toHaveValue("Creative coding");
    expect(screen.queryByRole("textbox", { name: "Interests" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Skills" }).closest("li")).toHaveAttribute(
      "data-active",
      "true",
    );
    expect(screen.getByText("Inferred")).toBeInTheDocument();
    expect(screen.getByText("Source: Portfolio")).toBeInTheDocument();
  });

  it("lets users edit every draft field and saves changes on blur", () => {
    const onChange = vi.fn();
    render(
      <DraftDocument
        fields={[{ id: "name", label: "Name", value: "Ada", status: "candidate" }]}
        onChange={onChange}
        title="Course application"
      />,
    );

    const field = screen.getByRole("textbox", { name: "Name" });
    expect(field).toHaveAttribute("rows", "1");
    Object.defineProperty(field, "scrollHeight", { configurable: true, value: 72 });
    fireEvent.change(field, { target: { value: "Grace Hopper" } });
    expect(field).toHaveStyle({ height: "72px" });
    fireEvent.blur(field);
    expect(field).toHaveValue("Grace Hopper");
    expect(onChange).toHaveBeenCalledWith("name", "Grace Hopper");
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
