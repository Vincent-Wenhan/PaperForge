"""Cheap in-process observability counters.

Backend timestamps and deltas (provider TTFT, event persist time, build
duration, stream gap total) are tracked here as monotonic gauges. There is no
external monitoring pipeline; this is a lightweight, always-on set of counters
that can be surfaced via a /metrics endpoint or logged. Per the doc, the p95
latency *targets* below are next-round goals, not measured benchmarks.

Single-process in-memory counters; swap for a real exports/prom backend
when PaperForge is ever deployed multi-worker.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Any


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        # name -> list of raw durations (ms), capped per metric.
        self._durations: dict[str, list[float]] = defaultdict(list)
        self._counters: dict[str, int] = defaultdict(int)
        self._max_duration_samples = 500

    def record_duration(self, name: str, seconds: float) -> None:
        ms = seconds * 1000.0
        with self._lock:
            bucket = self._durations[name]
            bucket.append(ms)
            if len(bucket) > self._max_duration_samples:
                del bucket[: len(bucket) - self._max_duration_samples]

    def increment(self, name: str, delta: int = 1) -> None:
        with self._lock:
            self._counters[name] += delta

    def _percentile(self, values: list[float], p: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        # Nearest-rank: p-th percentile is the ceil(p * n)-th largest.
        rank = max(1, int(p * len(ordered) + 0.999999))
        return round(ordered[min(len(ordered) - 1, rank - 1)], 2)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            durations = {
                name: {
                    "count": len(vals),
                    "p50_ms": self._percentile(vals, 0.50),
                    "p95_ms": self._percentile(vals, 0.95),
                    "max_ms": round(max(vals), 2) if vals else 0.0,
                }
                for name, vals in self._durations.items()
            }
            counters = dict(self._counters)
        return {"durations": durations, "counters": counters}


_registry: MetricsRegistry | None = None


def get_metrics() -> MetricsRegistry:
    global _registry
    if _registry is None:
        _registry = MetricsRegistry()
    return _registry
