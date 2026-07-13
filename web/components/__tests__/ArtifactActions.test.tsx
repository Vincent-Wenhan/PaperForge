import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ArtifactCard } from "../ArtifactCard";

vi.mock("@/lib/api", () => ({
  api: {
    renameArtifact: vi.fn().mockResolvedValue(undefined),
    downloadArtifact: vi.fn().mockResolvedValue(new Blob(["{}"])),
    deleteArtifact: vi.fn().mockResolvedValue(undefined),
  },
}));

import { api } from "@/lib/api";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Artifact actions", () => {
  it("shows menu items when ··· is clicked", () => {
    render(
      <ArtifactCard type="capability_card" path="x.json" artifactId="art_1" />,
    );
    const menuBtn = screen.getByLabelText(/Actions for/);
    fireEvent.click(menuBtn);
    expect(screen.getByRole("menuitem", { name: /Open/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /Use as context/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /Rename/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /Download/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /Delete/ })).toBeInTheDocument();
  });

  it("clicking Rename calls api.renameArtifact with prompt value", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("New Name");
    const onRenamed = vi.fn();
    render(
      <ArtifactCard
        type="capability_card"
        path="x.json"
        artifactId="art_1"
        onRenamed={onRenamed}
      />,
    );
    fireEvent.click(screen.getByLabelText(/Actions for/));
    fireEvent.click(screen.getByRole("menuitem", { name: /Rename/ }));
    await waitFor(() => expect(api.renameArtifact).toHaveBeenCalledWith("art_1", "New Name"));
    expect(onRenamed).toHaveBeenCalled();
  });

  it("Rename does nothing if prompt is cancelled", async () => {
    vi.spyOn(window, "prompt").mockReturnValue(null);
    render(
      <ArtifactCard type="capability_card" path="x.json" artifactId="art_1" />,
    );
    fireEvent.click(screen.getByLabelText(/Actions for/));
    fireEvent.click(screen.getByRole("menuitem", { name: /Rename/ }));
    expect(api.renameArtifact).not.toHaveBeenCalled();
  });

  it("clicking Download calls api.downloadArtifact", async () => {
    render(
      <ArtifactCard type="capability_card" path="x.json" artifactId="art_1" />,
    );
    fireEvent.click(screen.getByLabelText(/Actions for/));
    fireEvent.click(screen.getByRole("menuitem", { name: /Download/ }));
    await waitFor(() => expect(api.downloadArtifact).toHaveBeenCalledWith("art_1"));
  });

  it("clicking Delete with confirm calls api.deleteArtifact", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onDeleted = vi.fn();
    render(
      <ArtifactCard
        type="capability_card"
        path="x.json"
        artifactId="art_1"
        onDeleted={onDeleted}
      />,
    );
    fireEvent.click(screen.getByLabelText(/Actions for/));
    fireEvent.click(screen.getByRole("menuitem", { name: /Delete/ }));
    await waitFor(() => expect(api.deleteArtifact).toHaveBeenCalledWith("art_1"));
    expect(onDeleted).toHaveBeenCalled();
  });

  it("Delete cancelled when confirm returns false", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <ArtifactCard type="capability_card" path="x.json" artifactId="art_1" />,
    );
    fireEvent.click(screen.getByLabelText(/Actions for/));
    fireEvent.click(screen.getByRole("menuitem", { name: /Delete/ }));
    expect(api.deleteArtifact).not.toHaveBeenCalled();
  });

  it("Use as context adds attachment to store", () => {
    render(
      <ArtifactCard type="capability_card" path="x.json" artifactId="art_1" />,
    );
    fireEvent.click(screen.getByLabelText(/Actions for/));
    fireEvent.click(screen.getByRole("menuitem", { name: /Use as context/ }));
  });
});
