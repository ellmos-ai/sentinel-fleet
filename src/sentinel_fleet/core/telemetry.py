"""OpenTelemetry Tracing, Telemetry Spans & Circuit Breaker."""

import time
import logging
import uuid
from collections import deque
from contextvars import ContextVar, Token
from typing import Any, Deque, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field
from sentinel_fleet.core.access import RequestPrincipal, current_request_principal
from sentinel_fleet.core.config import settings
from sentinel_fleet.core.storage import BaseStore, get_store

logger = logging.getLogger(__name__)

# Ring buffer bound: the dashboard only ever reads the tail, an unbounded list leaks.
MAX_RETAINED_SPANS = 500

# SentinelFleet currently serves one organization. Keeping the identifier explicit in every
# span prevents "organization" from accidentally meaning "every tenant" when another
# organization is added later.
DEFAULT_ORGANIZATION_ID = "sentinel-demo"
SYSTEM_TELEMETRY_OWNER = "system:sentinel-fleet"
LEGACY_TELEMETRY_OWNER = "system:legacy-unassigned"
LEGACY_ORGANIZATION_ID = "legacy:unassigned"
REDACTED_VALUE = "[redacted]"

_SENSITIVE_ATTRIBUTE_KEYS = frozenset({
    "content", "document", "file", "filename", "file_name", "message", "path",
    "prompt", "task_name", "url", "workflow",
})
_USER_NAMED_SPAN_PREFIXES = ("queue_task:", "swarm_workflow:")

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
    # Missing fields on a pre-migration row do not become organization-visible. They load as
    # an unreachable private legacy owner and remain available only to trusted internal audits.
    owner_id: str = LEGACY_TELEMETRY_OWNER
    organization_id: str = LEGACY_ORGANIZATION_ID
    department_id: Optional[str] = None
    visibility: Literal["private", "department", "organization"] = "private"
    start_time: float
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    events: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "OK"
    error_message: Optional[str] = None


# The gate-ledger row of the tool call that is currently executing. The gateway binds it around
# every tool body, so code deep inside a domain module can leave evidence on the very row the
# operator is looking at, without being handed the span or having to know the agent id.
# A ContextVar rather than a module global: race lanes run concurrently on one event loop, and a
# global would file lane 2's verdict under lane 1's call.
_active_span: ContextVar[Optional["SpanRecord"]] = ContextVar("sentinel_active_span", default=None)


def _otel_safe_attributes(agent_id: str, attributes: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """OpenTelemetry only accepts primitive attribute values; stringify anything else."""
    safe: Dict[str, Any] = {"agent.id": agent_id}
    for key, value in _sanitize_mapping(attributes).items():
        safe[key] = value if isinstance(value, (str, bool, int, float)) else str(value)
    return safe


def _sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_ATTRIBUTE_KEYS or any(
        normalized.endswith(f"_{suffix}")
        for suffix in ("content", "document", "filename", "message", "path", "prompt", "url")
    )


def _sanitize_mapping(values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep operational metadata while removing user-selected content and locators.

    The same helper feeds both the durable record and the OpenTelemetry exporter. Redacting only
    the dashboard copy would still send the secret to Cloud Trace.
    """
    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(child_key): (
                    REDACTED_VALUE if _sensitive_key(str(child_key)) else clean(child_value)
                )
                for child_key, child_value in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return value

    return {
        str(key): REDACTED_VALUE if _sensitive_key(str(key)) else clean(value)
        for key, value in (values or {}).items()
    }


def _sanitize_span_name(name: str) -> str:
    for prefix in _USER_NAMED_SPAN_PREFIXES:
        if name.startswith(prefix):
            return f"{prefix}{REDACTED_VALUE}"
    return name


def _safe_error_message(status: str, error: Optional[str]) -> Optional[str]:
    # Exceptions may contain source URLs, uploaded filenames, local paths, model output or
    # document fragments. The task/result record owns detailed errors under its own ACL; the
    # cross-cutting telemetry record stores only the category.
    return f"{status}: details redacted" if error else None


class TelemetryService:
    """OpenTelemetry tracing plus a durable audit record for the dashboard.

    ``store`` is optional so small isolated services in unit tests remain memory-only.  The
    application singleton supplies the configured JSON/Firestore store.
    """

    def __init__(self, store: Optional[BaseStore[SpanRecord]] = None):
        self._store = store
        self.spans: Deque[SpanRecord] = deque(maxlen=MAX_RETAINED_SPANS)
        if self._store is not None:
            restored = sorted(self._store.list_all(), key=lambda span: span.start_time)
            self.spans.extend(restored[-MAX_RETAINED_SPANS:])
        self.active_trace_id: str = f"trace-{int(time.time()*1000)}"
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
        """Attach the locked Cloud Trace exporter when the deployment enables it."""
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

    def start_span(
        self,
        name: str,
        agent_id: str,
        attributes: Optional[Dict[str, Any]] = None,
        *,
        principal: Optional[RequestPrincipal] = None,
        organization_id: Optional[str] = None,
        visibility: Optional[Literal["private", "department", "organization"]] = None,
    ) -> SpanRecord:
        principal = principal or current_request_principal()
        if principal is None:
            resolved_organization = organization_id or DEFAULT_ORGANIZATION_ID
            owner_id = SYSTEM_TELEMETRY_OWNER
            department_id = None
            resolved_visibility = visibility or "organization"
        else:
            if organization_id and organization_id != principal.organization_id:
                raise ValueError("Telemetry organization cannot override the request principal")
            resolved_organization = principal.organization_id
            owner_id = principal.data_owner_id
            department_id = principal.department
            resolved_visibility = visibility or "private"
        if resolved_visibility == "department" and not department_id:
            raise ValueError("Department-visible telemetry requires a principal with a department")

        safe_name = _sanitize_span_name(name)
        safe_attributes = _sanitize_mapping(attributes)
        # A process-local counter reused ids after every cold start and overwrote a durable row.
        span_id = f"span-{uuid.uuid4().hex[:16]}"
        trace_id = self.active_trace_id

        if self._tracer is not None:
            otel_span = self._tracer.start_span(
                safe_name,
                attributes=_otel_safe_attributes(agent_id, {
                    **safe_attributes,
                    "sentinel.owner_id": owner_id,
                    "sentinel.organization_id": resolved_organization,
                    "sentinel.department_id": department_id or "",
                    "sentinel.visibility": resolved_visibility,
                }),
            )
            self._live_otel_spans[span_id] = otel_span
            # Surface the real W3C trace id, so dashboard rows match exported traces
            trace_id = format(otel_span.get_span_context().trace_id, "032x")

        record = SpanRecord(
            span_id=span_id,
            trace_id=trace_id,
            name=safe_name,
            agent_id=agent_id,
            owner_id=owner_id,
            organization_id=resolved_organization,
            department_id=department_id,
            visibility=resolved_visibility,
            start_time=time.time(),
            attributes=safe_attributes,
        )
        self.spans.append(record)
        self._persist(record)
        return record

    def _persist(self, span: SpanRecord) -> None:
        if self._store is not None:
            self._store.put(span.span_id, span)
            self._prune_persisted_organization(span.organization_id)

    def _prune_persisted_organization(self, organization_id: str) -> None:
        """Keep a durable per-tenant tail instead of an unbounded global collection.

        A global cap lets a busy tenant erase every dashboard row of a quiet tenant.  Retaining
        the newest ``MAX_RETAINED_SPANS`` rows per organization gives each tenant the same
        bounded audit window while still placing a hard bound on that tenant's storage use.
        """
        if self._store is None:
            return
        organization_rows = sorted(
            (
                row
                for row in self._store.list_all()
                if row.organization_id == organization_id
            ),
            key=lambda row: (row.start_time, row.span_id),
        )
        for expired in organization_rows[:-MAX_RETAINED_SPANS]:
            self._store.delete(expired.span_id)

    def end_span(self, span: SpanRecord, status: str = "OK", error: Optional[str] = None):
        span.end_time = time.time()
        span.status = status
        safe_error = _safe_error_message(status, error)
        span.error_message = safe_error
        self._persist(span)

        otel_span = self._live_otel_spans.pop(span.span_id, None)
        if otel_span is None:
            return

        otel_span.set_attribute("sentinel.status", status)
        if self._status_cls is not None:
            if safe_error:
                otel_span.set_status(self._status_cls(self._status_code_cls.ERROR, safe_error))
            else:
                otel_span.set_status(self._status_cls(self._status_code_cls.OK))
        otel_span.end()

    def add_event(self, span: SpanRecord, event_name: str, payload: Optional[Dict[str, Any]] = None):
        safe_payload = _sanitize_mapping(payload)
        span.events.append({
            "name": event_name,
            "timestamp": time.time(),
            "payload": safe_payload,
        })
        self._persist(span)
        otel_span = self._live_otel_spans.get(span.span_id)
        if otel_span is not None:
            otel_span.add_event(
                event_name, attributes=_otel_safe_attributes(span.agent_id, safe_payload)
            )

    def bind_active_span(self, span: SpanRecord) -> Token:
        """Mark a span as the one the current tool call runs under. Release it in a finally."""
        return _active_span.set(span)

    def release_active_span(self, token: Token) -> None:
        _active_span.reset(token)

    def record_on_active_span(self, event_name: str, payload: Optional[Dict[str, Any]] = None) -> bool:
        """Attach an event to the tool call currently in flight, if there is one.

        Returns whether it landed. A no-op outside the gateway is intended, not a silent loss:
        domain modules are also exercised directly by tests and must not require a span to run.
        """
        span = _active_span.get()
        if span is None:
            return False
        self.add_event(span, event_name, payload)
        return True

    @staticmethod
    def can_read(
        span: SpanRecord,
        *,
        requested_by: str,
        requested_department: Optional[str],
        requested_organization: str,
    ) -> bool:
        if span.organization_id != requested_organization:
            return False
        if span.visibility == "organization":
            return True
        if span.visibility == "department":
            return bool(requested_department) and span.department_id == requested_department
        return span.owner_id == requested_by

    def get_recent_spans(
        self,
        limit: int = 50,
        *,
        principal: Optional[RequestPrincipal] = None,
        requested_by: Optional[str] = None,
        requested_department: Optional[str] = None,
        requested_organization: Optional[str] = None,
    ) -> List[SpanRecord]:
        """Newest records, optionally filtered at the tenant boundary.

        No identity arguments is the trusted internal control-plane view retained for existing
        aggregators and tests. HTTP/API callers must pass ``principal=...``; a raw owner filter
        additionally requires an explicit organization so it cannot silently become global.
        """
        # Read the durable source when present.  The process-local deque is intentionally a
        # global tail for operational dashboards, so filtering that tail could make a quiet
        # tenant look empty after another tenant produced enough spans.
        rows = (
            self._store.list_all()
            if self._store is not None
            else list(self.spans)
        )
        rows.sort(key=lambda span: (span.start_time, span.span_id))
        if principal is not None:
            if (
                requested_organization
                and requested_organization != principal.organization_id
            ):
                raise ValueError("Telemetry organization cannot override the request principal")
            requested_by = principal.data_owner_id
            requested_department = principal.department
            requested_organization = principal.organization_id
        if requested_by is None and (requested_department or requested_organization):
            raise ValueError("A telemetry visibility query requires requested_by")
        if requested_by is not None:
            if not requested_organization:
                raise ValueError("A telemetry visibility query requires requested_organization")
            rows = [
                span for span in rows
                if self.can_read(
                    span,
                    requested_by=requested_by,
                    requested_department=requested_department,
                    requested_organization=requested_organization,
                )
            ]
        return list(reversed(rows[-limit:]))

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

    def get_persisted_span_total(self) -> int:
        """Number of durable dashboard records, or the retained memory count without a store."""
        return self._store.count() if self._store is not None else len(self.spans)


telemetry = TelemetryService(store=get_store("telemetry_spans", SpanRecord))
