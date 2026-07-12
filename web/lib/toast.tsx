"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";

export interface Toast {
  id: string;
  title: string;
  description?: string;
  variant?: "default" | "success" | "error";
}

interface ToastContextValue {
  toasts: Toast[];
  toast: (t: Omit<Toast, "id">) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    if (timers.current[id]) {
      clearTimeout(timers.current[id]);
      delete timers.current[id];
    }
  }, []);

  const toast = useCallback(
    (t: Omit<Toast, "id">) => {
      const id = `t_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      setToasts((prev) => [...prev, { ...t, id }]);
      timers.current[id] = setTimeout(() => dismiss(id), 4000);
      return id;
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={{ toasts, toast, dismiss }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`p-3 border rounded shadow-lg bg-background animate-slide-in ${
              t.variant === "success"
                ? "border-success"
                : t.variant === "error"
                  ? "border-destructive"
                  : "border-border"
            }`}
            role="status"
          >
            <div className="font-medium text-sm">{t.title}</div>
            {t.description && (
              <div className="text-xs text-muted-foreground mt-0.5">
                {t.description}
              </div>
            )}
            <button
              onClick={() => dismiss(t.id)}
              className="absolute top-1 right-2 text-muted-foreground hover:text-foreground text-xs"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // Ponytail: graceful fallback if no provider — return no-op so UI doesn't crash.
    return {
      toast: () => "",
      dismiss: () => {},
      toasts: [] as Toast[],
    };
  }
  return ctx;
}
