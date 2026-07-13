import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ToolPart, ArtifactPart, ErrorPart } from "../MessageParts";

describe("ToolPart", () => {
  it("renders tool name in summary", () => {
    render(<ToolPart name="verify_app" args={{}} callId="tc_1" />);
    expect(screen.getByText("Verifying app")).toBeInTheDocument();
  });

  it("clicking header toggles expanded details", () => {
    render(<ToolPart name="verify_app" args={{ app_path: "/app" }} callId="tc_1" />);
    const btn = screen.getByRole("button");
    fireEvent.click(btn);
    expect(screen.getByText(/Call ID/)).toBeInTheDocument();
  });
});

describe("ArtifactPart", () => {
  it("renders artifactId", () => {
    render(<ArtifactPart artifactId="art_123" />);
    expect(screen.getByText(/art_123/)).toBeInTheDocument();
  });
});

describe("ErrorPart", () => {
  it("renders the error message", () => {
    render(<ErrorPart message="build failed" />);
    expect(screen.getByText(/build failed/)).toBeInTheDocument();
  });
});
