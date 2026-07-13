import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Composer } from "../Composer";
import { useAppStore } from "@/lib/store";
import type { Run } from "@/lib/store";

const run: Run = {
  id: "run_1",
  title: "Test Run",
  status: "active",
  phase: "init",
  created_at: new Date().toISOString(),
};

beforeEach(() => {
  useAppStore.setState({
    currentRun: run,
    attachments: [],
    isRunning: false,
    composerPrefill: "",
    messages: [],
  });
});

describe("Composer attachment chips", () => {
  it("shows nothing when no attachments", () => {
    render(<Composer />);
    expect(screen.queryByText(/×/)).not.toBeInTheDocument();
  });

  it("renders a chip with name and remove button", () => {
    useAppStore.setState({
      attachments: [
        { id: "att1", type: "paper", name: "MedAgent.pdf", paperId: "p1" },
      ],
    });
    render(<Composer />);
    expect(screen.getByText("MedAgent.pdf")).toBeInTheDocument();
    expect(screen.getByLabelText("Remove MedAgent.pdf")).toBeInTheDocument();
  });

  it("clicking the chip × button removes the attachment", () => {
    const removeAttachment = vi.fn();
    useAppStore.setState({
      attachments: [
        { id: "att1", type: "paper", name: "MedAgent.pdf", paperId: "p1" },
      ],
      removeAttachment,
    });
    render(<Composer />);
    fireEvent.click(screen.getByLabelText("Remove MedAgent.pdf"));
    expect(removeAttachment).toHaveBeenCalledWith("att1");
  });
});
