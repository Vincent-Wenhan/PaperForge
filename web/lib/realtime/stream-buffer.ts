// Batches message deltas into a single store update per animation frame,
// reducing React re-renders during LLM streaming.
import { useAppStore } from "@/lib/store";

const pending = new Map<string, { text: string; taskId?: string }>();

let frameId: number | null = null;

export function enqueueMessageDelta(messageId: string, delta: string, taskId?: string) {
  if (!delta) return;

  const existing = pending.get(messageId);
  if (existing) {
    existing.text += delta;
    if (taskId) existing.taskId = taskId;
  } else {
    pending.set(messageId, { text: delta, taskId });
  }

  if (frameId !== null) return;

  frameId = requestAnimationFrame(() => {
    const store = useAppStore.getState();
    for (const [id, item] of pending) {
      store.appendMessageDelta(id, item.text, item.taskId);
    }
    pending.clear();
    frameId = null;
  });
}

export function flushMessageDeltas() {
  if (frameId !== null) {
    cancelAnimationFrame(frameId);
    frameId = null;
  }

  const store = useAppStore.getState();
  for (const [id, item] of pending) {
    store.appendMessageDelta(id, item.text, item.taskId);
  }
  pending.clear();
}
