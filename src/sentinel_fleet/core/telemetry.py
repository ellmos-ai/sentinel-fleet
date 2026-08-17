"""OpenTelemetry Tracing, Telemetry Spans & Circuit Breaker."""

import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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


class TelemetryService:
    def __init__(self):
        self.spans: List[SpanRecord] = []
        self.active_trace_id: str = f"trace-{int(time.time()*1000)}"

    def start_span(self, name: str, agent_id: str, attributes: Optional[Dict[str, Any]] = None) -> SpanRecord:
        span_id = f"span-{len(self.spans)+1:04d}"
        record = SpanRecord(
            span_id=span_id,
            trace_id=self.active_trace_id,
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

    def add_event(self, span: SpanRecord, event_name: str, payload: Optional[Dict[str, Any]] = None):
        span.events.append({
            "name": event_name,
            "timestamp": time.time(),
            "payload": payload or {}
        })

    def get_recent_spans(self, limit: int = 50) -> List[SpanRecord]:
        return list(reversed(self.spans[-limit:]))


telemetry = TelemetryService()
