"""Online authorization gate for the packaged TikTok RPA."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import socket
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


APP_ID = "tiktok_bd_auto"
APP_VERSION = "1.0"
CONFIG_FILE_NAME = "auth_config.json"

EMBEDDED_AUTH_API_URL = "http://8.134.92.143:8000/api/authorize"


class AuthorizationError(Exception):
    """Raised when the current machine is not authorized to run the RPA."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False))


def _candidate_config_paths() -> list[Path]:
    paths = [
        Path.cwd() / CONFIG_FILE_NAME,
        Path(__file__).resolve().parent / CONFIG_FILE_NAME,
    ]
    if _is_packaged():
        paths.insert(0, Path(sys.executable).resolve().parent / CONFIG_FILE_NAME)
    return paths


def _load_file_config() -> dict:
    for path in _candidate_config_paths():
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except json.JSONDecodeError as exc:
            raise AuthorizationError(f"Authorization config is invalid JSON: {path}") from exc
    return {}


def _get_setting(config: dict, key: str, env_name: str, default: str = "") -> str:
    env_value = os.getenv(env_name)
    if env_value is not None:
        return env_value
    value = config.get(key, default)
    return "" if value is None else str(value)


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
    return f"{socket.gethostname()}/{getpass.getuser()}"


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
    """Stop the RPA unless the authorization service allows this machine.

    In packaged exe mode, authorization is always enabled and the server URL is
    embedded at build time. The local config only supplies the license key.
    """
    config = _load_file_config()
    packaged = _is_packaged()
    enabled = "true" if packaged else _get_setting(config, "enabled", "RPA_AUTH_ENABLED", "false")
    if not _truthy(enabled):
        print("[AUTH] Online authorization is disabled. Set RPA_AUTH_ENABLED=1 to enable it.")
        return

    api_url = EMBEDDED_AUTH_API_URL.strip() if packaged else _get_setting(config, "api_url", "RPA_AUTH_API_URL").strip()
    if not api_url:
        raise AuthorizationError("Embedded authorization server URL is not configured.")

    license_key = _get_setting(config, "license_key", "RPA_LICENSE_KEY").strip()
    if not license_key and not packaged:
        license_key = input("Please enter license key: ").strip()
    if not license_key:
        raise AuthorizationError("Authorization config is missing license_key.")

    timeout_seconds = float(_get_setting(config, "timeout_seconds", "RPA_AUTH_TIMEOUT_SECONDS", "8"))
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
