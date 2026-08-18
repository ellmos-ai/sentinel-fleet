"""OpenTelemetry Tracing, Telemetry Spans & Circuit Breaker."""

import time
import logging
import itertools
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from sentinel_fleet.core.config import settings

logger = logging.getLogger(__name__)

# Ring buffer bound: the dashboard only ever reads the tail, an unbounded list leaks.
MAX_RETAINED_SPANS = 500

try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.trace import Status, StatusCode
    OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only in installs without the SDK
    OTEL_AVAILABLE = False


if OTEL_AVAILABLE:

    class BoundedSpanExporter(SpanExporter):
        """Collects exported spans in a ring buffer and counts everything it ever saw.

        The stock InMemorySpanExporter keeps every span forever, which is the same leak the
        dashboard buffer was fixed for. Retention is bounded; the total stays exact.
        """

        def __init__(self, max_spans: int = MAX_RETAINED_SPANS):
            self._spans = deque(maxlen=max_spans)
            self.exported_total = 0

        def export(self, spans):
            for span in spans:
                self._spans.append(span)
                self.exported_total += 1
            return SpanExportResult.SUCCESS

        def get_finished_spans(self):
            return tuple(self._spans)

        def force_flush(self, timeout_millis: int = 30_000) -> bool:
            return True

        def shutdown(self):
            self._spans.clear()


class SpanRecord(BaseModel):
    span_id: str
    trace_id: str
    name: str
    agent_id: str
    start_time: float
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    events: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "OK"
    error_message: Optional[str] = None


def _otel_safe_attributes(agent_id: str, attributes: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """OpenTelemetry only accepts primitive attribute values; stringify anything else."""
    safe: Dict[str, Any] = {"agent.id": agent_id}
    for key, value in (attributes or {}).items():
        safe[key] = value if isinstance(value, (str, bool, int, float)) else str(value)
    return safe


class TelemetryService:
    """Dual-sink tracing: real OpenTelemetry spans plus a bounded record list for the dashboard."""

    def __init__(self):
        self.spans: Deque[SpanRecord] = deque(maxlen=MAX_RETAINED_SPANS)
        self.active_trace_id: str = f"trace-{int(time.time()*1000)}"
        self._span_counter = itertools.count(1)
        self._live_otel_spans: Dict[str, Any] = {}
        self._tracer = None
        self._exporter = None
        self._status_cls = None
        self._status_code_cls = None
        self._init_opentelemetry()

    def _init_opentelemetry(self):
        if not OTEL_AVAILABLE:
            logger.warning(
                "opentelemetry-sdk is not installed - dashboard span records only, no OTel spans emitted"
            )
            return

        provider = TracerProvider(
            resource=Resource.create({SERVICE_NAME: settings.app_name.lower()})
        )
        self._exporter = BoundedSpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(self._exporter))

        if settings.enable_cloud_trace:
            self._attach_cloud_trace(provider)

        # Register globally so any auto-instrumentation attaches to the same provider.
        try:
            otel_trace.set_tracer_provider(provider)
        except Exception as exc:  # pragma: no cover - only on repeated provider registration
            logger.warning("Could not register the global tracer provider: %s", exc)

        self._tracer = provider.get_tracer("sentinel_fleet")
        self._status_cls = Status
        self._status_code_cls = StatusCode

    def _attach_cloud_trace(self, provider):
        """Cloud Trace export is optional: never make the app depend on a GCP-only package."""
        try:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            logger.warning(
                "ENABLE_CLOUD_TRACE is set but opentelemetry-exporter-gcp-trace is not installed - "
                "spans stay local"
            )
            return
        try:
            provider.add_span_processor(
                BatchSpanProcessor(CloudTraceSpanExporter(project_id=settings.google_cloud_project))
            )
            logger.info("Cloud Trace exporter attached for project %s", settings.google_cloud_project)
        except Exception as exc:
            logger.warning("Cloud Trace exporter could not be initialised: %s", exc)

    @property
    def otel_enabled(self) -> bool:
        return self._tracer is not None

    def start_span(self, name: str, agent_id: str, attributes: Optional[Dict[str, Any]] = None) -> SpanRecord:
        span_id = f"span-{next(self._span_counter):04d}"
        trace_id = self.active_trace_id

        if self._tracer is not None:
            otel_span = self._tracer.start_span(
                name, attributes=_otel_safe_attributes(agent_id, attributes)
            )
            self._live_otel_spans[span_id] = otel_span
            # Surface the real W3C trace id, so dashboard rows match exported traces
            trace_id = format(otel_span.get_span_context().trace_id, "032x")

        record = SpanRecord(
            span_id=span_id,
            trace_id=trace_id,
            name=name,
            agent_id=agent_id,
            start_time=time.time(),
            attributes=attributes or {}
        )
        self.spans.append(record)
        return record

    def end_span(self, span: SpanRecord, status: str = "OK", error: Optional[str] = None):
        span.end_time = time.time()
        span.status = status
        span.error_message = error

        otel_span = self._live_otel_spans.pop(span.span_id, None)
        if otel_span is None:
            return

        otel_span.set_attribute("sentinel.status", status)
        if self._status_cls is not None:
            if error:
                otel_span.set_status(self._status_cls(self._status_code_cls.ERROR, error))
            else:
                otel_span.set_status(self._status_cls(self._status_code_cls.OK))
        otel_span.end()

    def add_event(self, span: SpanRecord, event_name: str, payload: Optional[Dict[str, Any]] = None):
        span.events.append({
            "name": event_name,
            "timestamp": time.time(),
            "payload": payload or {}
        })
        otel_span = self._live_otel_spans.get(span.span_id)
        if otel_span is not None:
            otel_span.add_event(event_name, attributes=_otel_safe_attributes(span.agent_id, payload))

    def get_recent_spans(self, limit: int = 50) -> List[SpanRecord]:
        return list(reversed(list(self.spans)[-limit:]))

    def get_exported_spans(self) -> Tuple[str, ...]:
        """Names of the retained exported spans - evidence, not a claim (bounded, see exporter)."""
        if self._exporter is None:
            return ()
        return tuple(s.name for s in self._exporter.get_finished_spans())

    def get_exported_span_total(self) -> int:
        """Every span the exporter ever received, including the ones the ring buffer dropped."""
        if self._exporter is None:
            return 0
        return self._exporter.exported_total


telemetry = TelemetryService()
