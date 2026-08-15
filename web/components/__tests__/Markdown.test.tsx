import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Markdown } from "../Markdown";

describe("Markdown code blocks", () => {
  it("renders inline code without copying a code block button", () => {
    const { container } = render(<Markdown content="run `npm test` to verify" />);
    expect(container.querySelector("code")).toBeTruthy();
    expect(screen.queryByLabelText("Copy code")).toBeNull();
  });

  it("renders a fenced code block with a copy button", () => {
    render(<Markdown content={"```js\nconsole.log('hi')\n```"} />);
    expect(screen.getByLabelText("Copy code")).toBeVisible();
  });

  it("copies the code block content to clipboard", async () => {
    const writeText = vi.fn();
    Object.assign(navigator, { clipboard: { writeText } });
    render(<Markdown content={"```js\nconst x = 1;\n```"} />);
    await userEvent.click(screen.getByLabelText("Copy code"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("const x = 1;"));
  });
});
