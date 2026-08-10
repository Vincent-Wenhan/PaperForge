// Batches message deltas into a single store update per animation frame,
// reducing React re-renders during LLM streaming.
import { useAppStore } from "@/lib/store";

const pending = new Map<string, string>();

let frameId: number | null = null;

export function enqueueMessageDelta(messageId: string, delta: string) {
  if (!delta) return;

  pending.set(messageId, (pending.get(messageId) ?? "") + delta);

  if (frameId !== null) return;

  frameId = requestAnimationFrame(() => {
    const store = useAppStore.getState();
    for (const [id, text] of pending) {
      store.appendMessageDelta(id, text);
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
  for (const [id, text] of pending) {
    store.appendMessageDelta(id, text);
  }
  pending.clear();
}
