"""Unit tests for the OpenTelemetry instrumentation and its bounded buffers."""

from sentinel_fleet.core.telemetry import MAX_RETAINED_SPANS, TelemetryService


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
    assert span.error_message == "not scoped"
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
