"use client";

export function WorkbenchRail({ onClose }: { onClose: () => void }) {
  return (
    <div className="w-9 border-l border-border bg-muted/30 flex flex-col items-center py-2 gap-1">
      <button
        onClick={onClose}
        title="Close workbench"
        aria-label="Close workbench"
        className="text-xs text-muted-foreground hover:text-foreground"
      >
        ››
      </button>
    </div>
  );
}
