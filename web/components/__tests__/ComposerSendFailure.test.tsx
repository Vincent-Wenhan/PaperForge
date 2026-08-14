import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Composer } from "../Composer";
import { ToastProvider } from "@/lib/toast";
import { useAppStore } from "@/lib/store";
import type { Run } from "@/lib/store";

const run: Run = {
  id: "run_1",
  title: "Test Run",
  status: "active",
  phase: "init",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

vi.mock("@/lib/api", () => ({
  api: { sendMessage: vi.fn() },
  ApiError: class extends Error {},
}));
import { api as mockApi } from "@/lib/api";

function renderComposer() {
  return render(
    <ToastProvider>
      <Composer />
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.setState({
    currentRun: run,
    attachments: [],
    isRunning: false,
    composerPrefill: "",
    messages: [],
  });
  // deterministic optimistic id
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    value: { randomUUID: () => "opt_msg" },
  });
});

describe("Composer send failure", () => {
  it("keeps the user message with failed status and shows the reason", async () => {
    vi.mocked(mockApi.sendMessage).mockRejectedValue(new Error("network down"));

    renderComposer();
    fireEvent.change(screen.getByPlaceholderText(/Ask PaperForge/i), {
      target: { value: "Hello world" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send/i }));

    // The failure surfaces a Retry banner and keeps the optimistic user message.
    await waitFor(() => {
      expect(screen.getByTestId("send-failed-banner")).toBeVisible();
    });
    const msg = useAppStore.getState().messages[0];
    expect(msg.role).toBe("user");
    expect(msg.content).toBe("Hello world");
    expect(msg.status).toBe("failed");
    expect(msg.error).toBe("network down");
  });

  it("reuses the stable idempotency key on retry (no duplicate message)", async () => {
    vi.mocked(mockApi.sendMessage)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        status: "queued",
        run_id: "run_1",
        message: { id: "1", public_id: "opt_msg", content: "Hello" },
        task: { id: "task_1", status: "queued" },
        task_id: "task_1",
        event_cursor: 3,
      });

    renderComposer();
    fireEvent.change(screen.getByPlaceholderText(/Ask PaperForge/i), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send/i }));

    await waitFor(() => {
      expect(screen.getByTestId("send-failed-banner")).toBeVisible();
    });
    fireEvent.click(screen.getByTestId("send-retry"));

    await waitFor(() => {
      expect(mockApi.sendMessage).toHaveBeenCalledTimes(2);
    });
    // First call (original) and retry must both use the same public_id key.
    const args = vi.mocked(mockApi.sendMessage).mock.calls.map((c) => c[3]);
    expect(args[0]).toBe("opt_msg");
    expect(args[1]).toBe("opt_msg");
    // Only one user message survives, never a duplicate.
    expect(useAppStore.getState().messages.filter((m) => m.role === "user").length).toBe(1);
  });
});
