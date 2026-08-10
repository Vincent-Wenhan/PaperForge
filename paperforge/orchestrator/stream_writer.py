"""StreamWriter: coalesces provider deltas into bounded messages.

Small text chunks from the LLM provider are buffered and flushed to the
event bus every ~40ms (or once 24 chars accumulate), while durable message
content is checkpointed to storage at a slower 250ms cadence. This avoids a
SQLite UPDATE + durable append per tiny delta.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamWriter:
    run_id: str
    message_id: str
    storage: Any
    emit: Any

    flush_interval_s: float = 0.040
    checkpoint_interval_s: float = 0.250
    min_flush_chars: int = 24

    _pending: list[str] = field(default_factory=list)
    _full: list[str] = field(default_factory=list)
    _pending_chars: int = 0

    _last_flush_at: float = field(default_factory=time.monotonic)
    _last_checkpoint_at: float = field(default_factory=time.monotonic)

    async def push_text(self, text: str) -> None:
        if not text:
            return

        self._pending.append(text)
        self._full.append(text)
        self._pending_chars += len(text)

        now = time.monotonic()

        if (
            self._pending_chars >= self.min_flush_chars
            or now - self._last_flush_at >= self.flush_interval_s
        ):
            await self.flush_delta()

        if now - self._last_checkpoint_at >= self.checkpoint_interval_s:
            await self.checkpoint()

    async def flush_delta(self) -> None:
        if not self._pending:
            return

        delta = "".join(self._pending)
        self._pending.clear()
        self._pending_chars = 0
        self._last_flush_at = time.monotonic()

        await self.emit.message_delta(self.message_id, delta)

    async def checkpoint(self) -> None:
        content = "".join(self._full)
        await asyncio.to_thread(
            self.storage.update_streaming_message_content,
            self.message_id,
            content,
        )
        self._last_checkpoint_at = time.monotonic()

    async def finish(
        self,
        tool_calls: list[Any] | None = None,
    ) -> str:
        await self.flush_delta()

        content = "".join(self._full)

        await asyncio.to_thread(
            self.storage.complete_message,
            self.message_id,
            content,
            [
                {"id": tc.id, "name": tc.name, "args": tc.args}
                for tc in (tool_calls or [])
            ]
            or None,
        )

        await self.emit.message_completed(self.message_id, content)

        return content
