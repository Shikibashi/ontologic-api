"""Authentication helper utilities shared across routers."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Dict, Optional, Tuple

from fastapi import Depends, Request

from app.core.auth_config import current_user_optional
from app.core.logger import log
from app.core.user_models import User


def validate_token_format(auth_header: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validate Authorization header follows Bearer JWT format."""
    if not auth_header:
        return False, "Authorization header missing"

    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False, "Authorization header must start with 'Bearer'"

    token = parts[1].strip()
    if token.count(".") != 2:
        return False, "JWT token must contain three segments"

    return True, None


def decode_jwt_payload(token: str) -> Optional[Dict[str, Any]]:
    """Decode JWT payload without signature verification for debugging only."""
    try:
        payload_segment = token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        decoded_bytes = base64.urlsafe_b64decode(payload_segment + padding)
        return json.loads(decoded_bytes)
    except (IndexError, json.JSONDecodeError, ValueError, binascii.Error) as exc:
        log.debug("Unable to decode JWT payload for debugging: %s", exc)
        return None


async def get_optional_user_with_logging(
    request: Request,
    user: Optional[User] = Depends(current_user_optional),
) -> Optional[User]:
    """Dependency wrapper that adds observability around optional authentication."""

    auth_header = request.headers.get("authorization")
    is_valid_header, validation_error = validate_token_format(auth_header)

    if auth_header:
        header_preview = auth_header[:20]
        if len(auth_header) > 20:
            header_preview = f"{header_preview}..."
        log.debug(
            "Auth helper received Authorization header: preview=%s valid_format=%s",
            header_preview,
            is_valid_header,
        )
    else:
        log.debug("Auth helper invoked without Authorization header")

    if not is_valid_header and auth_header:
        log.warning("Authorization header failed validation: %s", validation_error)

    if auth_header and is_valid_header:
        token = auth_header.split(" ", 1)[1].strip()
        payload = decode_jwt_payload(token)
        if payload:
            log.debug(
                "JWT payload preview: sub=%s exp=%s issued_at=%s",
                payload.get("sub"),
                payload.get("exp"),
                payload.get("iat"),
            )

    if user is None:
        if auth_header:
            log.warning(
                "Optional authentication returned None despite Authorization header; token may be invalid, expired, or user missing."
            )
        else:
            log.debug("Optional authentication returned None with no Authorization header present")
        return None

    log.info(
        "Optional authentication resolved user: id=%s email=%s is_active=%s",
        getattr(user, "id", "unknown"),
        user.email,
        getattr(user, "is_active", "unknown"),
    )
    return user


def get_username_from_user(user: User) -> str:
    """
    Extract username from authenticated user object.

    Prioritizes user.username field, falls back to email prefix if username is not set.
    The caller should ensure ``user`` is not ``None`` when optional authentication is used.
    """

    if user.username:
        return user.username
    return user.email.split("@")[0]
