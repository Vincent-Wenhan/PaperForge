import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RunRow } from "../Sidebar";
import type { Run } from "@/lib/store";

const run: Run = {
  id: "run_1",
  title: "My Run",
  status: "active",
  phase: "init",
  created_at: new Date().toISOString(),
  pinned: false,
};

function renderRow(overrides: Partial<Parameters<typeof RunRow>[0]> = {}) {
  const handlers = {
    onSelect: vi.fn(),
    onToggleMenu: vi.fn(),
    onStartRename: vi.fn(),
    onRenameChange: vi.fn(),
    onRenameCommit: vi.fn(),
    onRenameCancel: vi.fn(),
    onArchive: vi.fn(),
    onDelete: vi.fn(),
    onTogglePin: vi.fn(),
  };
  const props = {
    run,
    menuOpen: false,
    renaming: false,
    renameValue: "",
    ...handlers,
    ...overrides,
  };
  return { ...handlers, props, result: render(<RunRow {...props} />) };
}

describe("RunRow context menu", () => {
  it("renders run title and status", () => {
    renderRow();
    expect(screen.getByText("My Run")).toBeInTheDocument();
    expect(screen.getByText(/active · init/)).toBeInTheDocument();
  });

  it("clicking the row triggers onSelect", () => {
    const { onSelect, result } = renderRow();
    const btn = result.container.querySelector("button");
    expect(btn).toBeTruthy();
    fireEvent.click(btn!);
    expect(onSelect).toHaveBeenCalled();
  });

  it("shows Rename, Pin, Archive, Delete when menu is open", () => {
    renderRow({ menuOpen: true });
    expect(screen.getByText("Rename")).toBeInTheDocument();
    expect(screen.getByText("Pin")).toBeInTheDocument();
    expect(screen.getByText("Archive")).toBeInTheDocument();
    expect(screen.getByText("Delete")).toBeInTheDocument();
  });

  it("shows Unpin when already pinned", () => {
    renderRow({
      menuOpen: true,
      run: { ...run, pinned: true },
    });
    expect(screen.getByText("Unpin")).toBeInTheDocument();
  });

  it("clicking Rename enters edit mode via onStartRename", () => {
    const { onStartRename } = renderRow({ menuOpen: true });
    fireEvent.click(screen.getByText("Rename"));
    expect(onStartRename).toHaveBeenCalled();
  });

  it("rename input commits on Enter and cancels on Escape", () => {
    const { onRenameCommit, onRenameCancel } = renderRow({
      renaming: true,
      renameValue: "Renamed",
    });
    const input = screen.getByDisplayValue("Renamed") as HTMLInputElement;
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRenameCommit).toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onRenameCancel).toHaveBeenCalled();
  });
});
