import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  api: {
    getFileTree: vi.fn().mockResolvedValue({ tree: [] }),
    readFile: vi.fn().mockResolvedValue({ content: "" }),
    writeFile: vi.fn().mockResolvedValue(undefined),
    createEntry: vi.fn().mockResolvedValue(undefined),
    renameEntry: vi.fn().mockResolvedValue(undefined),
    deleteEntry: vi.fn().mockResolvedValue(undefined),
    restartSandbox: vi.fn().mockResolvedValue(undefined),
    stopSandbox: vi.fn().mockResolvedValue(undefined),
    getPreviewUrl: (id: string) => `/preview/${id}`,
  },
}));

vi.mock("@monaco-editor/react", () => ({
  default: ({ children }: any) => <div>{children}</div>,
}));

import { PreviewPanel } from "../PreviewPanel";
import { useAppStore } from "@/lib/store";
import { api } from "@/lib/api";

const sandbox = {
  id: "sb_1",
  run_id: "run_1",
  container_id: "container_1",
  preview_port: 3001,
  status: "running",
};

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.setState({
    sandbox,
    artifacts: [],
    currentRun: null,
    activeTab: "preview",
  });
});

describe("Preview status toolbar", () => {
  it("renders toolbar with Refresh, Restart, Open, Stop buttons when sandbox is running", async () => {
    await act(async () => {
      render(<PreviewPanel />);
    });
    expect(screen.getByTitle("Refresh")).toBeInTheDocument();
    expect(screen.getByTitle("Restart sandbox")).toBeInTheDocument();
    expect(screen.getByTitle("Open in new tab")).toBeInTheDocument();
    expect(screen.getByTitle("Stop sandbox")).toBeInTheDocument();
  });

  it("clicking Restart calls api.restartSandbox", async () => {
    await act(async () => {
      render(<PreviewPanel />);
    });
    act(() => fireEvent.click(screen.getByTitle("Restart sandbox")));
    await waitFor(() =>
      expect(api.restartSandbox).toHaveBeenCalledWith("sb_1"),
    );
  });

  it("clicking Stop calls api.stopSandbox", async () => {
    await act(async () => {
      render(<PreviewPanel />);
    });
    act(() => fireEvent.click(screen.getByTitle("Stop sandbox")));
    await waitFor(() => expect(api.stopSandbox).toHaveBeenCalledWith("sb_1"));
  });

  it("displays sandbox status in toolbar", async () => {
    await act(async () => {
      render(<PreviewPanel />);
    });
    expect(screen.getByText(/Sandbox: running/)).toBeInTheDocument();
  });

  it("viewport buttons toggle desktop/tablet/mobile", async () => {
    await act(async () => {
      render(<PreviewPanel />);
    });
    const desktop = screen.getByTitle("desktop");
    const tablet = screen.getByTitle("tablet");
    act(() => fireEvent.click(tablet));
    expect(tablet).toHaveAttribute("aria-pressed", "true");
    act(() => fireEvent.click(desktop));
    expect(desktop).toHaveAttribute("aria-pressed", "true");
  });
});
