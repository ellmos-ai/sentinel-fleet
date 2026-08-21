"""Verified request principals and fail-closed IAP identity mapping."""

import base64
import json
import time

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from google.oauth2 import id_token

from sentinel_fleet.core.access import (
    IAP_CERTS_URL,
    IAP_ISSUER,
    WORKSPACE_COOKIE,
    VerifiedIapIdentity,
    demo_principal,
    resolve_iap_user_id,
    valid_workspace_token,
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


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def test_iap_assertion_passes_real_rsa_verification_and_rejects_tampering():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    now = int(time.time())
    audience = "/projects/7/global/backendServices/9"
    header = _b64url(json.dumps({"alg": "RS256", "kid": "test-key"}).encode())
    payload = _b64url(json.dumps({
        "iss": IAP_ISSUER,
        "sub": "signed-subject",
        "email": "signed@example.org",
        "aud": audience,
        "iat": now - 5,
        "exp": now + 60,
    }).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    token = f"{header}.{payload}.{_b64url(signature)}"

    class Response:
        status = 200
        data = json.dumps({"test-key": public_pem}).encode("utf-8")

    def request(_url, method="GET", **_kwargs):
        assert method == "GET"
        return Response()

    def crypto_verifier(value, **kwargs):
        return id_token.verify_token(value, request, **kwargs)

    identity = verify_iap_assertion(token, audience, crypto_verifier)
    assert identity == VerifiedIapIdentity(
        subject="signed-subject", email="signed@example.org"
    )

    tampered_payload = _b64url(json.dumps({
        "iss": IAP_ISSUER,
        "sub": "attacker",
        "email": "attacker@example.org",
        "aud": audience,
        "iat": now - 5,
        "exp": now + 60,
    }).encode())
    with pytest.raises(ValueError):
        verify_iap_assertion(
            f"{header}.{tampered_payload}.{_b64url(signature)}",
            audience,
            crypto_verifier,
        )


def test_iap_mapping_accepts_only_an_explicit_registered_mapping_key():
    identity = VerifiedIapIdentity(subject="subject-7", email="user@example.org")
    assert resolve_iap_user_id('{"sub:subject-7":"operator"}', identity) == "operator"
    assert resolve_iap_user_id('{"email:user@example.org":"operator"}', identity) == "operator"
    with pytest.raises(PermissionError):
        resolve_iap_user_id('{"email:someone-else@example.org":"operator"}', identity)


def test_demo_share_handle_does_not_disclose_or_reuse_the_workspace_cookie():
    token = "0123456789abcdef0123456789abcdef"
    principal = demo_principal("member:demo", token)

    assert token not in principal.data_owner_id
    assert principal.data_owner_id.startswith("workspace:")
    assert valid_workspace_token(principal.data_owner_id) is None
    assert demo_principal("member:demo", token).data_owner_id == principal.data_owner_id


@pytest.mark.asyncio
async def test_exposed_demo_share_handle_cannot_be_replayed_as_a_workspace_cookie(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as owner:
        owner_access = (await owner.get("/api/access/me")).json()
        assert "data_owner_id" not in owner_access
        exposed_handle = owner_access["share_id"]

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={WORKSPACE_COOKIE: exposed_handle.removeprefix("workspace:")},
    ) as attacker:
        attacker_access = (await attacker.get("/api/access/me")).json()

    assert attacker_access["share_id"] != exposed_handle


@pytest.mark.asyncio
async def test_production_demo_workspace_cookie_is_secure_behind_tls_proxy(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "environment", "production")

    async with AsyncClient(
        transport=ASGITransport(app=server.app), base_url="http://internal-cloud-run"
    ) as client:
        response = await client.get("/api/access/me")

    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{WORKSPACE_COOKIE}=")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" in set_cookie


@pytest.mark.asyncio
async def test_cloud_run_workspace_cookie_is_secure_with_default_environment(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setenv("K_SERVICE", "sentinel-fleet")

    async with AsyncClient(
        transport=ASGITransport(app=server.app), base_url="http://internal-cloud-run"
    ) as client:
        response = await client.get("/api/access/me")

    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{WORKSPACE_COOKIE}=")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" in set_cookie


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
            "share_id": "operator",
            "organization_id": "sentinel-demo",
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
    headers = {
        "X-Goog-IAP-JWT-Assertion": "signed.jwt",
        "Origin": "https://test",
    }

    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="https://test") as client:
        created = server.prompt_registry.create_prompt(
            title="IAP admin probe",
            purpose="Verify authenticated administration",
            category="test",
            text="Before",
            variables=[],
            tags=[],
            owner_id="admin:lukas",
            organization_id="sentinel-demo",
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

    with pytest.raises(WebSocketDisconnect) as cross_site:
        with client.websocket_connect("/ws/run/TASK-MISSING"):
            pass
    assert cross_site.value.code == 4403

    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(
            "/ws/run/TASK-MISSING",
            headers={"Origin": "http://testserver"},
        ):
            pass
    assert denied.value.code == 4401

    with pytest.raises(WebSocketDisconnect) as authenticated:
        with client.websocket_connect(
            "/ws/run/TASK-MISSING",
            headers={
                "X-Goog-IAP-JWT-Assertion": "signed.jwt",
                "Origin": "http://testserver",
            },
        ):
            pass
    assert authenticated.value.code == 4404


@pytest.mark.asyncio
async def test_non_demo_rejects_cross_site_mutation_even_with_valid_iap(monkeypatch):
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
    async with AsyncClient(
        transport=ASGITransport(app=server.app), base_url="https://test"
    ) as client:
        response = await client.post(
            "/api/users",
            headers={
                "X-Goog-IAP-JWT-Assertion": "signed.jwt",
                "Origin": "https://evil.example",
            },
            json={
                "user_id": "csrf-probe",
                "display_name": "CSRF Probe",
                "email": "csrf@example.test",
                "profile_id": "member",
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site or origin-less mutation refused."
