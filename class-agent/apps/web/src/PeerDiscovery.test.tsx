import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  PeerDiscovery,
  type PeerDiscoveryData,
  type PeerDiscoveryProps,
} from "@class-agent/ui";

export const peerFixture: PeerDiscoveryData = {
  memory: {
    profile: {
      goal: "Museum voice agent",
      challenges: ["Visitor control"],
      interests: ["Voice interfaces"],
    },
    profile_origin: "Student form",
    updated_at: "2026-11-08T20:00:00Z",
    feedback: [],
  },
  recommendations: [
    {
      build_id: "build-ada",
      reason: "Shows how visitors can choose when to continue.",
      borrow: "Use a pause and resume control.",
      evidence_quote: "Visitors choose when to continue.",
      profile: { goal: "Museum voice agent", challenges: [], interests: [] },
      created_at: "2026-11-08T20:00:00Z",
      build: {
        id: "build-ada",
        project_id: "agents2026-ada",
        title: "Voice companion",
        week: 6,
        source_url: "https://example.edu/ada/week06/",
        observed_at: "2026-11-08T20:00:00Z",
        truncated: false,
      },
    },
  ],
  coverage: {
    "agents2026-ada": { checked_at: "2026-11-08", status: "indexed" },
  },
  indexed_builds: 1,
  privacy: "Your learning needs are private.",
  freshness: "Manual refresh only.",
};
function setup(extra: Partial<PeerDiscoveryProps> = {}) {
  const props = {
    data: structuredClone(peerFixture),
    onSaveProfile: vi.fn(),
    onForget: vi.fn(),
    onFeedback: vi.fn(),
    onRefresh: vi.fn(),
    ...extra,
  };
  render(<PeerDiscovery {...props} />);
  return props;
}

describe("native peer discovery", () => {
  it("shows source evidence and records feedback only on explicit actions", () => {
    const p = setup();
    expect(screen.getByRole("link", { name: /Open original/ })).toHaveAttribute(
      "href",
      "https://example.edu/ada/week06/",
    );
    expect(p.onFeedback).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Not relevant" }));
    expect(p.onFeedback).toHaveBeenCalledWith({
      build_id: "build-ada",
      rating: "not_relevant",
      note: "",
    });
    fireEvent.click(screen.getByText("Why this recommendation?"));
    expect(screen.getByText("Visitors choose when to continue.")).toBeVisible();
  });
  it("saves student-edited memory and requires separate erase confirmation", () => {
    const p = setup({ view: "memory" });
    fireEvent.change(
      screen.getByLabelText("Current project or learning goal"),
      { target: { value: "Screen-free interaction" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Save my learning needs" }),
    );
    expect(p.onSaveProfile).toHaveBeenCalledWith({
      goal: "Screen-free interaction",
      challenges: ["Visitor control"],
      interests: ["Voice interfaces"],
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Forget my peer-learning memory" }),
    );
    expect(p.onForget).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    expect(p.onForget).toHaveBeenCalledOnce();
  });
  it("makes a contact draft without sending or posting feedback", () => {
    const p = setup();
    fireEvent.click(screen.getByRole("button", { name: /Message/ }));
    expect(
      (screen.getByLabelText("Your message") as HTMLTextAreaElement).value,
    ).toContain("Voice companion");
    expect(screen.getByText(/Nothing has been sent/)).toBeVisible();
    expect(p.onFeedback).not.toHaveBeenCalled();
  });
  it("refreshes only explicitly entered projects and weeks", () => {
    const p = setup({ view: "coverage" });
    fireEvent.click(screen.getByText("Manage source refresh"));
    fireEvent.change(screen.getByLabelText(/Course project IDs/), {
      target: { value: "agents2026-ada\nagents2026-grace" },
    });
    fireEvent.change(screen.getByLabelText(/Weeks ·/), {
      target: { value: "5,6" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh selected sources" }),
    );
    expect(p.onRefresh).toHaveBeenCalledWith(
      ["agents2026-ada", "agents2026-grace"],
      [5, 6],
    );
  });
});

const shownPair = {mine:"a",peer:"b",borrow:"The sensor reports every second.",reason:"Both builds explore how feedback changes the next action."};
const atlas = {
  ownAuthor:"mine",
  authors:[{id:"mine",name:"Raine",site:"https://example.edu/raine/",mark:0},{id:"peer",name:"Ada",site:"https://example.edu/ada/",mark:1}],
  builds:[{id:"a",author:"mine",title:"Garden",week:3,domain:"Memory",url:"https://example.edu/raine/3"},
          {id:"b",author:"peer",title:"Sensor board",week:3,domain:"Memory",url:"https://example.edu/ada/3"},
          {id:"c",author:"peer",title:"Camera",week:4,domain:"Memory",url:"https://example.edu/ada/4"}],
  pairs:[shownPair],
};
it("groups a domain across the published lecture weeks", () => {
  setup({data:{...peerFixture,atlas}});
  fireEvent.click(screen.getByRole("button",{name:"Domains"}));
  fireEvent.click(screen.getByRole("button",{name:/Memory.*3 builds/}));
  expect(screen.queryByRole("combobox",{name:"Week"})).not.toBeInTheDocument();
  expect(screen.getByRole("heading",{name:/Week 4 · Agent environments/})).toBeVisible();
  expect(screen.getByRole("heading",{name:/Week 3 · Human-agent/})).toBeVisible();
});
it("shows the agent's result set and sends only the student's edited message", async () => {
  const sendMessage=vi.fn().mockResolvedValue(undefined);
  setup({data:{...peerFixture,atlas},matchedBuildIds:["b"],sendMessage});
  expect(screen.getByRole("heading",{name:"Sensor board"})).toBeVisible();
  expect(screen.queryByText("Camera")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"My Weekly Paired Stars"}));
  fireEvent.click(screen.getByRole("button",{name:"Connect"}));
  expect(screen.getByText(shownPair.reason)).toBeVisible();
  expect(screen.queryByText(shownPair.borrow)).not.toBeInTheDocument();
  expect(sendMessage).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Message to Ada"),{target:{value:"How did you test the board?"}});
  fireEvent.click(screen.getByRole("button",{name:"Send"}));
  expect(sendMessage).toHaveBeenCalledWith("b","How did you test the board?",expect.any(String));
  expect(await screen.findByText("Message sent.")).toBeVisible();
});
