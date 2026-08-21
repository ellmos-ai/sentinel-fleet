"""Verified request principals and fail-closed IAP identity mapping."""

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from sentinel_fleet.core.access import (
    IAP_CERTS_URL,
    IAP_ISSUER,
    VerifiedIapIdentity,
    resolve_iap_user_id,
    verify_iap_assertion,
)
from sentinel_fleet.core.config import settings
from sentinel_fleet.web import server


def test_iap_verifier_checks_signature_inputs_issuer_and_claims():
    seen = {}

    def verifier(token, **kwargs):
        seen.update(token=token, **kwargs)
        return {"iss": IAP_ISSUER, "sub": "subject-7", "email": "User@Example.org"}

    identity = verify_iap_assertion("signed.jwt", "/projects/7/global/backendServices/9", verifier)

    assert identity == VerifiedIapIdentity(subject="subject-7", email="user@example.org")
    assert seen == {
        "token": "signed.jwt",
        "audience": "/projects/7/global/backendServices/9",
        "certs_url": IAP_CERTS_URL,
    }

    with pytest.raises(ValueError, match="issuer"):
        verify_iap_assertion(
            "signed.jwt", "audience",
            lambda *_args, **_kwargs: {"iss": "forged", "sub": "x", "email": "x@y.test"},
        )


def test_iap_mapping_accepts_only_an_explicit_registered_mapping_key():
    identity = VerifiedIapIdentity(subject="subject-7", email="user@example.org")
    assert resolve_iap_user_id('{"sub:subject-7":"operator"}', identity) == "operator"
    assert resolve_iap_user_id('{"email:user@example.org":"operator"}', identity) == "operator"
    with pytest.raises(PermissionError):
        resolve_iap_user_id('{"email:someone-else@example.org":"operator"}', identity)


@pytest.mark.asyncio
async def test_non_demo_request_uses_verified_iap_principal(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "iap_audience", "expected-audience")
    monkeypatch.setattr(settings, "iap_user_map", '{"sub:subject-7":"operator"}')
    monkeypatch.setattr(
        server,
        "verify_iap_assertion",
        lambda assertion, audience: (
            VerifiedIapIdentity(subject="subject-7", email="operator@example.org")
            if assertion == "signed.jwt" and audience == "expected-audience"
            else (_ for _ in ()).throw(ValueError("bad assertion"))
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="https://test") as client:
        response = await client.get(
            "/api/access/me", headers={"X-Goog-IAP-JWT-Assertion": "signed.jwt"}
        )
        assert response.status_code == 200
        assert response.json() == {
            "data_owner_id": "operator",
            "department": "operations",
            "authenticated": True,
            "demo_workspace": False,
        }

        missing = await client.get("/api/access/me")
        assert missing.status_code == 401


@pytest.mark.asyncio
async def test_non_demo_authenticated_admin_can_use_an_admin_mutation(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "iap_audience", "expected-audience")
    monkeypatch.setattr(settings, "iap_user_map", '{"sub:admin-subject":"admin:lukas"}')
    monkeypatch.setattr(
        server,
        "verify_iap_assertion",
        lambda _assertion, _audience: VerifiedIapIdentity(
            subject="admin-subject", email="admin@example.org"
        ),
    )
    headers = {"X-Goog-IAP-JWT-Assertion": "signed.jwt"}

    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="https://test") as client:
        created = server.prompt_registry.create_prompt(
            title="IAP admin probe",
            purpose="Verify authenticated administration",
            category="test",
            text="Before",
            variables=[],
            tags=[],
        )
        try:
            response = await client.post(
                f"/api/prompts/{created.id}/version",
                headers=headers,
                data={
                    "new_version_number": "1.1.0",
                    "new_text": "After",
                    "change_summary": "Verified IAP administrator",
                },
            )
            assert response.status_code == 200
        finally:
            server.prompt_registry.delete_prompt(created.id)


def test_non_demo_run_websocket_requires_the_same_signed_iap_principal(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "iap_audience", "expected-audience")
    monkeypatch.setattr(settings, "iap_user_map", '{"sub:subject-7":"operator"}')

    def verify(assertion, audience):
        if assertion != "signed.jwt" or audience != "expected-audience":
            raise ValueError("bad assertion")
        return VerifiedIapIdentity(subject="subject-7", email="operator@example.org")

    monkeypatch.setattr(server, "verify_iap_assertion", verify)
    client = TestClient(server.app)

    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect("/ws/run/TASK-MISSING"):
            pass
    assert denied.value.code == 4401

    with pytest.raises(WebSocketDisconnect) as authenticated:
        with client.websocket_connect(
            "/ws/run/TASK-MISSING",
            headers={"X-Goog-IAP-JWT-Assertion": "signed.jwt"},
        ):
            pass
    assert authenticated.value.code == 4404
