"""Tenant isolation and data-minimisation regressions for durable telemetry."""

import pytest

from sentinel_fleet.core.access import (
    RequestPrincipal,
    bind_request_principal,
    reset_request_principal,
)
from sentinel_fleet.core.storage import LocalJsonStore
from sentinel_fleet.core.telemetry import MAX_RETAINED_SPANS, SpanRecord, TelemetryService
from sentinel_fleet.domains.omniledger.extractor import MultimodalExtractor
from sentinel_fleet.domains.omniledger.local_text import LocalTextResult


def _principal(
    owner: str,
    department: str | None = None,
    organization: str = "sentinel-demo",
) -> RequestPrincipal:
    return RequestPrincipal(
        user_id=owner,
        data_owner_id=owner,
        authenticated=True,
        department=department,
        organization_id=organization,
    )


def _service() -> TelemetryService:
    return TelemetryService(store=LocalJsonStore("telemetry_scope_test", SpanRecord))


def test_start_span_binds_the_current_request_principal_by_default():
    service = _service()
    alice = _principal("user:alice", "finance")
    token = bind_request_principal(alice)
    try:
        span = service.start_span("chat:send", "agent:chat-operator")
    finally:
        reset_request_principal(token)

    assert span.owner_id == "user:alice"
    assert span.organization_id == "sentinel-demo"
    assert span.department_id == "finance"
    assert span.visibility == "private"


def test_two_principals_only_see_permitted_private_department_and_org_spans():
    service = _service()
    alice = _principal("user:alice", "finance", "org-a")
    bob = _principal("user:bob", "finance", "org-a")
    eve = _principal("user:eve", "legal", "org-a")
    mallory = _principal("user:mallory", "finance", "org-b")

    service.start_span("alice-private", "agent:test", principal=alice)
    service.start_span("bob-private", "agent:test", principal=bob)
    service.start_span(
        "finance-shared", "agent:test", principal=alice,
        visibility="department",
    )
    service.start_span(
        "org-a-shared", "agent:test", principal=alice,
        visibility="organization",
    )
    service.start_span(
        "org-b-shared", "agent:test", principal=mallory,
        visibility="organization",
    )

    alice_names = {
        span.name for span in service.get_recent_spans(principal=alice)
    }
    bob_names = {
        span.name for span in service.get_recent_spans(principal=bob)
    }
    eve_names = {
        span.name for span in service.get_recent_spans(principal=eve)
    }

    assert alice_names == {"alice-private", "finance-shared", "org-a-shared"}
    assert bob_names == {"bob-private", "finance-shared", "org-a-shared"}
    assert eve_names == {"org-a-shared"}
    assert "org-b-shared" not in alice_names | bob_names | eve_names


def test_legacy_span_without_scope_is_private_and_unassigned():
    legacy = SpanRecord(
        span_id="span-legacy",
        trace_id="trace-legacy",
        name="legacy",
        agent_id="agent:test",
        start_time=1.0,
    )

    assert legacy.owner_id == "system:legacy-unassigned"
    assert legacy.organization_id == "legacy:unassigned"
    assert legacy.visibility == "private"


def test_caller_cannot_override_the_bound_principals_organization():
    service = _service()
    alice = _principal("user:alice", "finance", "org-a")

    with pytest.raises(ValueError, match="cannot override"):
        service.start_span(
            "cross-org-write", "agent:test", principal=alice, organization_id="org-b"
        )
    with pytest.raises(ValueError, match="cannot override"):
        service.get_recent_spans(principal=alice, requested_organization="org-b")


def test_persisted_telemetry_redacts_user_selected_names_urls_documents_and_errors():
    service = _service()
    alice = _principal("user:alice", "finance")
    secret_name = "Board_Merger_Plan.pdf"
    secret_url = "https://intranet.example/board/merger"
    span = service.start_span(
        f"queue_task:{secret_name}",
        "agent:test",
        {
            "task_name": secret_name,
            "url": secret_url,
            "path": f"C:\\Private\\{secret_name}",
            "tool": "execute_template",
            "metadata": {"source_url": secret_url, "nested": [{"filename": secret_name}]},
        },
        principal=alice,
    )
    service.add_event(
        span,
        "web_page_inspected",
        {"url": secret_url, "document": secret_name, "verdict": "green"},
    )
    service.end_span(
        span,
        status="ERROR",
        error=f"Could not open C:\\Private\\{secret_name} from {secret_url}",
    )

    stored = span.model_dump_json()
    assert secret_name not in stored
    assert secret_url not in stored
    assert "C:\\\\Private" not in stored
    assert span.attributes["tool"] == "execute_template"
    assert span.error_message == "ERROR: details redacted"


def test_invoice_privacy_event_never_records_the_uploaded_filename():
    service = _service()
    span = service.start_span("tool_call:extract", "agent:test")
    token = service.bind_active_span(span)
    original = __import__(
        "sentinel_fleet.domains.omniledger.extractor", fromlist=["telemetry"]
    ).telemetry
    module = __import__(
        "sentinel_fleet.domains.omniledger.extractor", fromlist=["telemetry"]
    )
    module.telemetry = service
    try:
        MultimodalExtractor()._screen_before_dispatch(
            "Acquisition_Target.pdf",
            LocalTextResult(text="Invoice number 12", backend="test"),
            None,
        )
    finally:
        module.telemetry = original
        service.release_active_span(token)

    payload = span.events[0]["payload"]
    assert "document" not in payload
    assert "Acquisition_Target.pdf" not in span.model_dump_json()


def test_durable_retention_is_bounded_per_organization_without_hiding_quiet_tenant():
    store = LocalJsonStore("telemetry-retention-test", SpanRecord)
    service = TelemetryService(store=store)
    quiet = _principal("user:quiet", organization="org-quiet")
    busy = _principal("user:busy", organization="org-busy")

    quiet_span = service.start_span("quiet-visible", "agent:test", principal=quiet)
    service.end_span(quiet_span)
    for index in range(MAX_RETAINED_SPANS + 3):
        span = service.start_span(f"busy-{index}", "agent:test", principal=busy)
        service.end_span(span)

    assert [row.name for row in service.get_recent_spans(principal=quiet)] == [
        "quiet-visible"
    ]
    busy_rows = service.get_recent_spans(MAX_RETAINED_SPANS + 10, principal=busy)
    assert len(busy_rows) == MAX_RETAINED_SPANS
    retained_names = {row.name for row in busy_rows}
    assert "busy-502" in retained_names
    # Windows wall-clock timestamps have millisecond-sized ties, so the exact three rows evicted
    # from the oldest tied group are intentionally unspecified.
    assert len({f"busy-{index}" for index in range(10)} - retained_names) >= 1
    assert store.count() == MAX_RETAINED_SPANS + 1
