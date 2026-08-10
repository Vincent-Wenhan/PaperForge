"""Metrics registry self-check (doc 24)."""

from paperforge.observability.metrics import get_metrics


def demo() -> None:
    m = get_metrics()
    m.record_duration("provider_ttft_ms", 0.1)
    m.record_duration("provider_ttft_ms", 0.3)
    m.record_duration("event_persist_ms", 0.01)
    m.increment("stream_gap_total")
    m.increment("stream_gap_total")
    m.increment("build_total")

    snap = m.snapshot()
    assert snap["counters"]["stream_gap_total"] == 2
    assert snap["counters"]["build_total"] == 1
    ttft = snap["durations"]["provider_ttft_ms"]
    assert ttft["count"] == 2
    assert ttft["p50_ms"] == 100.0  # 0.1s -> 100ms

    # Fresh registry so the global doesn't leak across callers.
    from paperforge.observability.metrics import _registry

    _registry.registry = None  # type: ignore[attr-defined]
    print("metrics demo ok")


if __name__ == "__main__":
    demo()
