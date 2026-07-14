import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  api: {
    listAppTree: vi.fn().mockResolvedValue({
      tree: [{ path: "app/page.tsx", type: "file", size: 10 }],
    }),
    readAppFile: vi.fn().mockResolvedValue({
      path: "app/page.tsx",
      content: "export default function Page() {}",
    }),
    writeAppFile: vi.fn().mockResolvedValue({ saved: true }),
    getFileTree: vi.fn(),
    readFile: vi.fn(),
    writeFile: vi.fn(),
    restartSandbox: vi.fn(),
    stopSandbox: vi.fn(),
    getPreviewUrl: (id: string) => "/preview/" + id,
  },
}));

vi.mock("@monaco-editor/react", () => ({
  default: () => <div data-testid="monaco-editor">editor</div>,
}));

import { PreviewPanel } from "../PreviewPanel";
import { useAppStore } from "@/lib/store";
import { api } from "@/lib/api";

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.setState({
    currentRun: {
      id: "run_1",
      title: "Run",
      status: "active",
      created_at: "now",
      updated_at: "now",
    },
    sandbox: null,
    artifacts: [{ id: "app_1", type: "nextjs_app", run_id: "run_1" }],
    activeTab: "preview",
  } as any);
});

describe("app artifact workspace", () => {
  it("browses app files without requiring a running sandbox", async () => {
    render(<PreviewPanel />);
    fireEvent.click(screen.getByRole("tab", { name: "Code" }));

    await waitFor(() => expect(api.listAppTree).toHaveBeenCalledWith("app_1", "run_1"));
    expect(screen.getByText("page.tsx")).toBeInTheDocument();
  });
});
