"""Request-scoped data ownership for the public demonstration.

The public build deliberately has no human login.  Treating every browser as ``member:demo``
nevertheless made private records global.  A random HttpOnly workspace cookie is an object
capability: it does not claim a person's identity, but it gives one browser a stable, unguessable
owner id for private demo data.  Organization-wide seed data remains shared.

Non-demo deployments validate IAP's signed assertion and map it to a registered user. The demo
cookie remains workspace isolation only and must not be presented as SSO.
"""

import json
import re
import secrets
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


WORKSPACE_COOKIE = "sentinel_workspace"
IAP_ASSERTION_HEADER = "X-Goog-IAP-JWT-Assertion"
IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"
IAP_ISSUER = "https://cloud.google.com/iap"
_WORKSPACE_TOKEN = re.compile(r"^[a-f0-9]{32}$")


@dataclass(frozen=True)
class RequestPrincipal:
    """The capability actor and the narrower owner of private demo records."""

    user_id: str
    data_owner_id: str
    authenticated: bool = False
    department: Optional[str] = None
    email: Optional[str] = None
    subject: Optional[str] = None


@dataclass(frozen=True)
class VerifiedIapIdentity:
    subject: str
    email: str


_CURRENT_PRINCIPAL: ContextVar[Optional[RequestPrincipal]] = ContextVar(
    "sentinel_request_principal", default=None
)


def bind_request_principal(principal: RequestPrincipal) -> Token:
    return _CURRENT_PRINCIPAL.set(principal)


def reset_request_principal(token: Token) -> None:
    _CURRENT_PRINCIPAL.reset(token)


def current_request_principal() -> Optional[RequestPrincipal]:
    return _CURRENT_PRINCIPAL.get()


def valid_workspace_token(value: Optional[str]) -> Optional[str]:
    token = (value or "").strip().lower()
    return token if _WORKSPACE_TOKEN.fullmatch(token) else None


def new_workspace_token() -> str:
    return secrets.token_hex(16)


def demo_principal(user_id: str, token: str) -> RequestPrincipal:
    checked = valid_workspace_token(token)
    if checked is None:
        raise ValueError("A demo workspace token must be 128-bit lowercase hexadecimal.")
    return RequestPrincipal(
        user_id=user_id,
        data_owner_id=f"workspace:{checked}",
        authenticated=False,
    )


def verify_iap_assertion(
    assertion: str,
    audience: str,
    verifier: Optional[Callable[..., Dict[str, Any]]] = None,
) -> VerifiedIapIdentity:
    """Validate IAP's signed JWT, including its audience, issuer and identity claims."""
    if not assertion or not audience:
        raise ValueError("IAP assertion and IAP_AUDIENCE are required")
    if verifier is None:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        request_adapter = google_requests.Request()

        def verifier(token: str, **kwargs) -> Dict[str, Any]:
            return id_token.verify_token(token, request_adapter, **kwargs)

    claims = verifier(assertion, audience=audience, certs_url=IAP_CERTS_URL)
    if claims.get("iss") != IAP_ISSUER:
        raise ValueError("IAP assertion has an invalid issuer")
    subject = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    if not subject or not email:
        raise ValueError("IAP assertion is missing subject or email")
    return VerifiedIapIdentity(subject=subject, email=email)


def resolve_iap_user_id(mapping_json: str, identity: VerifiedIapIdentity) -> str:
    """Resolve signed IAP claims to an existing application user; never auto-provision."""
    try:
        mapping = json.loads(mapping_json or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"IAP_USER_MAP is not valid JSON: {exc}") from exc
    if not isinstance(mapping, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in mapping.items()
    ):
        raise ValueError("IAP_USER_MAP must be a JSON object of claim to user ID")
    normalized = {key.strip().lower(): value.strip() for key, value in mapping.items()}
    candidates = (
        f"sub:{identity.subject}".lower(),
        identity.subject.lower(),
        f"email:{identity.email}",
        identity.email,
    )
    for candidate in candidates:
        user_id = normalized.get(candidate)
        if user_id:
            return user_id
    raise PermissionError("The authenticated IAP identity is not mapped to a SentinelFleet user")


def authenticated_principal(
    *, user_id: str, department: Optional[str], identity: VerifiedIapIdentity
) -> RequestPrincipal:
    return RequestPrincipal(
        user_id=user_id,
        data_owner_id=user_id,
        authenticated=True,
        department=department,
        email=identity.email,
        subject=identity.subject,
    )
