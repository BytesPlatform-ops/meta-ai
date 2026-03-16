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


def _sign(user_id: str, nonce: str) -> str:
    msg = f"{user_id}:{nonce}".encode()
    return hmac.new(_KEY, msg, hashlib.sha256).hexdigest()


def generate_state(user_id: str) -> str:
    """Return a signed, URL-safe state token embedding the user_id."""
    nonce = secrets.token_hex(16)
    sig = _sign(user_id, nonce)
    raw = f"{user_id}:{nonce}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_state(state: str) -> str:
    """
    Verify the state token and return the user_id it contains.
    Raises ValueError on any tampering or malformed input.
    """
    try:
        raw = base64.urlsafe_b64decode(state.encode()).decode()
        user_id, nonce, provided_sig = raw.split(":", 2)
    except Exception:
        raise ValueError("Malformed state token")

    expected_sig = _sign(user_id, nonce)
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise ValueError("State token signature mismatch — possible CSRF attack")

    return user_id
