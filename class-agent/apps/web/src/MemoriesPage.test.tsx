import type { Memory } from "@class-agent/protocol";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api.js";
import { MemoriesPage } from "./MemoriesPage.js";

vi.mock("./api.js", () => ({
  deleteMemory: vi.fn(),
  listMemories: vi.fn(),
  updateMemory: vi.fn(),
}));

const memory = (id: string, content: string): Memory => ({
  id,
  user_id: "10000000-0000-4000-8000-000000000001",
  created_at: "2026-11-08T12:00:00Z",
  updated_at: "2026-11-08T12:00:00Z",
  kind: "preference",
  content,
  source_event_ids: [],
  privacy: "personal",
  metadata: {},
});
const first = memory("20000000-0000-4000-8000-000000000001", "Prefers hints");
const second = memory("20000000-0000-4000-8000-000000000002", "Studies sound design");

describe("MemoriesPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(api.listMemories).mockResolvedValue([first, second]);
  });

  it("explains an empty list", async () => {
    vi.mocked(api.listMemories).mockResolvedValue([]);
    render(<MemoriesPage onBack={vi.fn()} />);
    expect(await screen.findByText("The agent has not saved any memories yet.")).toBeVisible();
  });

  it("edits one memory and moves it to the top", async () => {
    vi.mocked(api.updateMemory).mockResolvedValue({ ...second, content: "Studies theater" });
    render(<MemoriesPage onBack={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: `Edit: ${second.content}` }));
    const box = screen.getByRole("textbox", { name: "Edit memory" });
    expect(box).toHaveValue(second.content);
    fireEvent.change(box, { target: { value: "  Studies theater  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Studies theater", { selector: "p" })).toBeVisible();
    expect(api.updateMemory).toHaveBeenCalledWith(second.id, "Studies theater");
    expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("Studies theater");
    expect(screen.queryByRole("textbox", { name: "Edit memory" })).toBeNull();
  });

  it("does not save a blank edit and can cancel", async () => {
    render(<MemoriesPage onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: `Edit: ${first.content}` }));
    fireEvent.change(screen.getByRole("textbox", { name: "Edit memory" }), {
      target: { value: "   " },
    });
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText(first.content)).toBeVisible();
    expect(api.updateMemory).not.toHaveBeenCalled();
  });

  it("deletes only after confirmation", async () => {
    vi.mocked(api.deleteMemory).mockResolvedValue();
    render(<MemoriesPage onBack={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: `Delete: ${first.content}` }));
    expect(api.deleteMemory).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Keep" }));
    expect(screen.getByText(first.content)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: `Delete: ${first.content}` }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));

    await waitFor(() => expect(screen.queryByText(first.content)).toBeNull());
    expect(api.deleteMemory).toHaveBeenCalledWith(first.id);
    expect(screen.getByText(second.content)).toBeVisible();
  });

  it("keeps the memory and reports a failed delete", async () => {
    vi.mocked(api.deleteMemory).mockRejectedValue(new Error("nope"));
    render(<MemoriesPage onBack={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: `Delete: ${first.content}` }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be deleted");
    expect(screen.getByText(first.content)).toBeVisible();
  });
});
