"use client";

import { useEffect, useRef, useState } from "react";

interface ResizableDividerProps {
  onResize: (delta: number) => void;
  direction?: "horizontal" | "vertical";
}

export function ResizableDivider({
  onResize,
  direction = "horizontal",
}: ResizableDividerProps) {
  const [dragging, setDragging] = useState(false);
  const lastPos = useRef(0);

  const handleDown = (e: React.MouseEvent) => {
    e.preventDefault();
    lastPos.current =
      direction === "horizontal" ? e.clientX : e.clientY;
    setDragging(true);
  };

  useEffect(() => {
    if (!dragging) return;

    const handleMove = (e: MouseEvent) => {
      const current =
        direction === "horizontal" ? e.clientX : e.clientY;
      const delta = current - lastPos.current;
      lastPos.current = current;
      if (delta !== 0) onResize(delta);
    };

    const handleUp = () => setDragging(false);

    document.body.style.cursor =
      direction === "horizontal" ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";

    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);

    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [dragging, direction, onResize]);

  return (
    <div
      role="separator"
      aria-orientation={
        direction === "horizontal" ? "vertical" : "horizontal"
      }
      onMouseDown={handleDown}
      className={`${
        direction === "horizontal"
          ? "w-1 cursor-col-resize"
          : "h-1 cursor-row-resize"
      } bg-border hover:bg-primary/40 transition-colors flex-shrink-0`}
    />
  );
}
