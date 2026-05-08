"""Online authorization gate for local RPA scripts.

The check is intentionally small and dependency-free so it can run before the
desktop automation imports heavier libraries or starts clicking.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import socket
import urllib.error
import urllib.request
import uuid


APP_ID = "tiktok_bd_auto"
APP_VERSION = "1.0"


class AuthorizationError(Exception):
    """Raised when the current machine is not authorized to run the RPA."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _build_device_id() -> str:
    raw = "|".join(
        [
            platform.node(),
            getpass.getuser(),
            str(uuid.getnode()),
            platform.platform(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_device_label() -> str:
    hostname = socket.gethostname()
    username = getpass.getuser()
    return f"{hostname}/{username}"


def _post_json(url: str, payload: dict, timeout_seconds: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response_body = response.read().decode("utf-8")
    return json.loads(response_body)


def enforce_authorization() -> None:
    """Stop the script unless the online authorization service allows it.

    Environment variables:
    - RPA_AUTH_ENABLED=1 enables the check.
    - RPA_AUTH_API_URL points to the authorization endpoint.
    - RPA_LICENSE_KEY stores the user's license key; otherwise input() asks.
    - RPA_AUTH_TIMEOUT_SECONDS customizes the request timeout.
    """
    if not _truthy(os.getenv("RPA_AUTH_ENABLED")):
        print("[AUTH] Online authorization is disabled. Set RPA_AUTH_ENABLED=1 to enable it.")
        return

    api_url = (os.getenv("RPA_AUTH_API_URL") or "").strip()
    if not api_url:
        raise AuthorizationError("RPA_AUTH_API_URL is required when RPA_AUTH_ENABLED=1.")

    license_key = (os.getenv("RPA_LICENSE_KEY") or "").strip()
    if not license_key:
        license_key = input("请输入授权码 / License key: ").strip()
    if not license_key:
        raise AuthorizationError("License key cannot be empty.")

    timeout_seconds = float(os.getenv("RPA_AUTH_TIMEOUT_SECONDS") or "8")
    payload = {
        "app_id": APP_ID,
        "app_version": APP_VERSION,
        "license_key": license_key,
        "device_id": _build_device_id(),
        "device_label": _build_device_label(),
    }

    try:
        result = _post_json(api_url, payload, timeout_seconds)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AuthorizationError(f"Authorization server rejected the request: {detail}") from exc
    except Exception as exc:
        raise AuthorizationError(f"Authorization check failed: {exc}") from exc

    if not bool(result.get("allowed")):
        reason = result.get("reason") or "not allowed"
        raise AuthorizationError(f"Authorization denied: {reason}")

    owner = result.get("owner") or "authorized user"
    expires_at = result.get("expires_at") or "no expiry"
    print(f"[AUTH] Authorized: {owner} | expires_at={expires_at}")
