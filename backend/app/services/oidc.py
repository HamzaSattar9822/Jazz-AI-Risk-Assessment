"""Microsoft Entra ID (OIDC) sign-in for SYRA."""

from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User
from app.security import create_token, hash_password

logger = logging.getLogger(__name__)

ROLE_RANK = {
    "admin": 40,
    "reviewer": 30,
    "governance": 30,
    "requester": 10,
}

_ROLE_ALIASES = {
    "requester": "requester",
    "submitter": "requester",
    "user": "requester",
    "reviewer": "reviewer",
    "raio": "reviewer",
    "governance": "governance",
    "admin": "admin",
    "administrator": "admin",
    "syra-requesters": "requester",
    "syra-reviewers": "reviewer",
    "syra-admins": "admin",
}


class OidcError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code


def _authority(settings: Settings) -> str:
    return f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0"


def _metadata_url(settings: Settings) -> str:
    return f"{_authority(settings)}/.well-known/openid-configuration"


def normalize_roles(raw: Any, allowed: set[str]) -> list[str]:
    values: list[Any]
    if raw is None:
        values = []
    elif isinstance(raw, str):
        values = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        values = [raw]

    roles: list[str] = []
    for item in values:
        key = str(item or "").strip().lower()
        mapped = _ROLE_ALIASES.get(key, key)
        if mapped in allowed or mapped in ROLE_RANK:
            if mapped not in roles:
                roles.append(mapped)
    if not roles:
        roles = ["requester"]
    # Keep only known app roles when an allow-list is configured.
    if allowed:
        filtered = [role for role in roles if role in allowed]
        roles = filtered or ["requester"]
    return roles


def primary_role(roles: list[str]) -> str:
    if not roles:
        return "requester"
    return max(roles, key=lambda role: ROLE_RANK.get(role, 0))


def user_roles(user: User) -> list[str]:
    stored = getattr(user, "roles", None) or []
    if isinstance(stored, str):
        stored = [part.strip() for part in stored.split(",") if part.strip()]
    if not isinstance(stored, list) or not stored:
        return [user.role] if user.role else ["requester"]
    return [str(role) for role in stored]


def user_has_role(user: User, *candidates: str) -> bool:
    owned = {role.lower() for role in user_roles(user)}
    return any(candidate.lower() in owned for candidate in candidates)


def build_authorize_url(settings: Settings, state: str) -> str:
    if not settings.entra_configured:
        raise OidcError("Entra ID SSO is not configured.", 503)
    query = urlencode(
        {
            "client_id": settings.entra_client_id,
            "response_type": "code",
            "redirect_uri": settings.entra_redirect_uri,
            "response_mode": "query",
            "scope": "openid profile email offline_access",
            "state": state,
            "prompt": "select_account",
        }
    )
    return (
        f"https://login.microsoftonline.com/{settings.entra_tenant_id}"
        f"/oauth2/v2.0/authorize?{query}"
    )


def create_oidc_state(settings: Settings) -> str:
    return jwt.encode(
        {"nonce": secrets.token_urlsafe(16), "typ": "oidc_state"},
        settings.jwt_secret,
        algorithm="HS256",
    )


def verify_oidc_state(settings: Settings, state: str) -> None:
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise OidcError("Invalid or expired sign-in state.", 400) from exc
    if payload.get("typ") != "oidc_state":
        raise OidcError("Invalid sign-in state.", 400)


def _load_metadata(settings: Settings) -> dict:
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(_metadata_url(settings))
            response.raise_for_status()
            return response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load Entra metadata: %s", exc)
        raise OidcError("Could not reach Entra ID metadata endpoint.", 502) from exc


def _decode_token(token: str, settings: Settings, jwks_uri: str, issuer: str) -> dict:
    jwks = PyJWKClient(jwks_uri)
    key = jwks.get_signing_key_from_jwt(token)
    # Entra may issue either v1 or v2 issuer forms depending on token version.
    issuers = {
        issuer,
        f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0",
        f"https://sts.windows.net/{settings.entra_tenant_id}/",
    }
    try:
        return jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=settings.entra_client_id,
            issuer=list(issuers),
            options={"verify_aud": True, "verify_iss": True},
        )
    except jwt.PyJWTError as exc:
        raise OidcError(f"Could not validate Entra token ({exc}).", 401) from exc


def exchange_code(settings: Settings, code: str) -> dict[str, Any]:
    metadata = _load_metadata(settings)
    token_endpoint = metadata.get("token_endpoint")
    jwks_uri = metadata.get("jwks_uri")
    issuer = metadata.get("issuer") or _authority(settings)
    if not token_endpoint or not jwks_uri:
        raise OidcError("Entra metadata is incomplete.", 502)

    data = {
        "client_id": settings.entra_client_id,
        "client_secret": settings.entra_client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.entra_redirect_uri,
        "scope": "openid profile email offline_access",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(token_endpoint, data=data)
    except Exception as exc:  # noqa: BLE001
        raise OidcError("Token exchange with Entra ID failed.", 502) from exc
    if response.status_code >= 400:
        detail = response.text[:240]
        raise OidcError(f"Entra token exchange failed ({response.status_code}): {detail}", 401)

    body = response.json()
    id_token = body.get("id_token")
    access_token = body.get("access_token")
    if not id_token:
        raise OidcError("Entra did not return an ID token.", 401)

    id_claims = _decode_token(id_token, settings, jwks_uri, issuer)
    access_claims: dict = {}
    if access_token:
        try:
            access_claims = _decode_token(access_token, settings, jwks_uri, issuer)
        except OidcError:
            # Access token audience can differ; still try roles from ID token.
            logger.info("Access token audience validation skipped for roles fallback")
            try:
                access_claims = jwt.decode(
                    access_token,
                    options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
                )
            except jwt.PyJWTError:
                access_claims = {}

    roles = normalize_roles(
        access_claims.get("roles") or id_claims.get("roles") or id_claims.get("role"),
        settings.entra_allowed_role_set,
    )
    email = (
        (id_claims.get("email") or id_claims.get("preferred_username") or id_claims.get("upn") or "")
        .strip()
        .lower()
    )
    if not email:
        raise OidcError("Entra token did not include an email claim.", 400)
    name = (
        id_claims.get("name")
        or id_claims.get("given_name")
        or email.split("@", 1)[0].replace(".", " ").title()
    )
    return {
        "email": email,
        "name": str(name),
        "roles": roles,
        "role": primary_role(roles),
        "claims": id_claims,
    }


def upsert_oidc_user(db: Session, profile: dict[str, Any]) -> User:
    email = profile["email"]
    user = db.scalar(select(User).where(User.email == email))
    roles = profile["roles"]
    role = profile["role"]
    if user is None:
        user = User(
            email=email,
            name=profile["name"],
            business_unit="",
            role=role,
            roles=roles,
            password_hash="oidc$disabled",
        )
        db.add(user)
    else:
        user.name = profile["name"] or user.name
        user.role = role
        user.roles = roles
        if not user.password_hash:
            user.password_hash = "oidc$disabled"
    db.commit()
    db.refresh(user)
    return user


def issue_session_token(user: User) -> str:
    return create_token(user.id)
