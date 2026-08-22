"""Unit tests for the OpenTelemetry instrumentation and its bounded buffers."""

from sentinel_fleet.core.telemetry import MAX_RETAINED_SPANS, TelemetryService
from sentinel_fleet.core.storage import LocalJsonStore
from sentinel_fleet.core.telemetry import SpanRecord


def test_spans_reach_the_opentelemetry_exporter():
    service = TelemetryService()
    assert service.otel_enabled is True

    span = service.start_span("tool_call:probe", "agent:test", {"tool": "probe"})
    service.add_event(span, "model_armor_sanitized", {"redactions": "completed"})
    service.end_span(span, status="OK")

    assert "tool_call:probe" in service.get_exported_spans()
    assert service.get_exported_span_total() >= 1
    # The dashboard record carries the real W3C trace id, not a synthetic one
    assert len(span.trace_id) == 32
    assert int(span.trace_id, 16) > 0


def test_error_status_is_propagated_to_the_span():
    service = TelemetryService()
    span = service.start_span("tool_call:failing", "agent:test")
    service.end_span(span, status="SECURITY_VIOLATION", error="not scoped")

    assert span.status == "SECURITY_VIOLATION"
    assert span.error_message == "SECURITY_VIOLATION: details redacted"
    assert "tool_call:failing" in service.get_exported_spans()


def test_both_buffers_are_bounded_and_ids_stay_unique():
    """Mi2: trimming must not recycle span ids, and neither buffer may grow without bound."""
    service = TelemetryService()
    overflow = MAX_RETAINED_SPANS + 25

    ids = []
    for i in range(overflow):
        span = service.start_span(f"tool_call:bulk_{i}", "agent:test")
        service.end_span(span)
        ids.append(span.span_id)

    assert len(set(ids)) == overflow, "span ids were reused after the buffer wrapped"
    assert len(service.spans) == MAX_RETAINED_SPANS
    assert len(service.get_exported_spans()) == MAX_RETAINED_SPANS
    # The dropped spans are still counted, so the number reported stays truthful
    assert service.get_exported_span_total() >= overflow


def test_dashboard_spans_survive_a_service_restart(tmp_path):
    """Regression: Firestore-backed records elsewhere survived while Telemetry became empty."""
    path = str(tmp_path / "telemetry.json")
    first_store = LocalJsonStore("telemetry_spans", SpanRecord, persistence_path=path)
    first = TelemetryService(store=first_store)
    span = first.start_span("tool_call:persisted", "agent:test")
    first.add_event(span, "evidence", {"verdict": "green"})
    first.end_span(span, status="OK")

    second_store = LocalJsonStore("telemetry_spans", SpanRecord, persistence_path=path)
    second = TelemetryService(store=second_store)
    restored = second.get_recent_spans()

    assert len(restored) == 1
    assert restored[0].name == "tool_call:persisted"
    assert restored[0].events[0]["name"] == "evidence"
    assert restored[0].end_time is not None
    assert second.get_persisted_span_total() == 1


def test_durable_prune_is_throttled_but_still_bounds_the_tail(tmp_path, monkeypatch):
    """Pruning used to stream the whole collection on EVERY persisted write.

    _persist fires from start_span, end_span and add_event, so against Firestore that was
    hundreds of document reads per tool call. The prune now runs on the first write per
    organization and then only every PRUNE_INTERVAL_WRITES writes; between prunes the durable
    tail may overshoot MAX_RETAINED_SPANS by at most that interval.
    """
    from sentinel_fleet.core import telemetry as telemetry_module
    from sentinel_fleet.core.storage import LocalJsonStore
    from sentinel_fleet.core.telemetry import PRUNE_INTERVAL_WRITES, SpanRecord

    class CountingStore(LocalJsonStore):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.list_all_calls = 0

        def list_all(self):
            self.list_all_calls += 1
            return super().list_all()

    monkeypatch.setattr(telemetry_module, "MAX_RETAINED_SPANS", 5)
    store = CountingStore(
        "telemetry_spans", SpanRecord, persistence_path=str(tmp_path / "spans.json")
    )
    service = TelemetryService(store=store)
    store.list_all_calls = 0  # restore-on-init is not the behavior under test

    persists = 0
    for i in range(30):
        span = service.start_span(f"tool_call:throttle_{i}", "agent:test")
        service.end_span(span)
        persists += 2

    expected_prunes = 1 + (persists - 1) // PRUNE_INTERVAL_WRITES
    assert store.list_all_calls <= expected_prunes + 1, (
        f"{store.list_all_calls} collection streams for {persists} writes - "
        "the prune is not throttled"
    )
    assert store.count() <= 5 + PRUNE_INTERVAL_WRITES, (
        "the durable tail must stay bounded by MAX_RETAINED_SPANS plus one prune interval"
    )
