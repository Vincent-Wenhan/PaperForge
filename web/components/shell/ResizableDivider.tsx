"use client";

import { useEffect, useRef, useState } from "react";

interface ResizableDividerProps {
  onResize: (delta: number) => void;
  direction?: "horizontal" | "vertical";
}

export function ResizableDivider({ onResize, direction = "horizontal" }: ResizableDividerProps) {
  const [dragging, setDragging] = useState(false);
  const lastPos = useRef(0);

  const handleDown = (e: React.MouseEvent) => {
    lastPos.current = direction === "horizontal" ? e.clientX : e.clientY;
    setDragging(true);
  };

  useEffect(() => {
    if (!dragging) return;
    const handleMove = (e: MouseEvent) => {
      const current = direction === "horizontal" ? e.clientX : e.clientY;
      const delta = current - lastPos.current;
      lastPos.current = current;
      if (delta !== 0) onResize(delta);
    };
    const handleUp = () => setDragging(false);
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
  }, [dragging, direction, onResize]);

  return (
    <div
      onMouseDown={handleDown}
      className={`${
        direction === "horizontal" ? "w-1 cursor-col-resize" : "h-1 cursor-row-resize"
      } bg-border hover:bg-primary/40 transition-colors flex-shrink-0`}
    />
  );
}
