"""
CSRF-safe OAuth state tokens.

Format (before base64):  <user_id>:<nonce>:<hmac_hex>

The HMAC binds the user_id + nonce to the SECRET_KEY so the callback
can:
  1. Verify the token hasn't been tampered with.
  2. Extract the user_id without a server-side session store.

This is stateless — no Redis or DB required.
"""
import base64
import hashlib
import hmac
import secrets

from .config import get_settings

_settings = get_settings()
_KEY = _settings.SECRET_KEY.encode()


def _sign(payload: str, nonce: str) -> str:
    msg = f"{payload}:{nonce}".encode()
    return hmac.new(_KEY, msg, hashlib.sha256).hexdigest()


def generate_state(user_id: str, workspace_id: str | None = None) -> str:
    """Return a signed, URL-safe state token embedding user_id and optional workspace_id."""
    nonce = secrets.token_hex(16)
    payload = f"{user_id}|{workspace_id or ''}"
    sig = _sign(payload, nonce)
    raw = f"{payload}:{nonce}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_state(state: str) -> tuple[str, str | None]:
    """
    Verify the state token and return (user_id, workspace_id).
    workspace_id may be None if not embedded.
    Raises ValueError on any tampering or malformed input.
    """
    try:
        raw = base64.urlsafe_b64decode(state.encode()).decode()
        payload, nonce, provided_sig = raw.split(":", 2)
    except Exception:
        raise ValueError("Malformed state token")

    expected_sig = _sign(payload, nonce)
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise ValueError("State token signature mismatch — possible CSRF attack")

    parts = payload.split("|", 1)
    user_id = parts[0]
    workspace_id = parts[1] if len(parts) > 1 and parts[1] else None
    return user_id, workspace_id
