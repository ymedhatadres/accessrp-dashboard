"""Magic-link auth gated to @adres.ae mailboxes.

Tokens are HMAC-SHA256-signed JSON payloads. They expire after TOKEN_TTL_SECONDS.
The signing key lives in .streamlit/secrets.toml — never commit it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import smtplib
import ssl
import time
import urllib.parse
from email.message import EmailMessage

import streamlit as st

ALLOWED_DOMAIN = "adres.ae"
TOKEN_TTL_SECONDS = 15 * 60
SESSION_KEY = "auth_user_email"


def is_allowed(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower().endswith("@" + ALLOWED_DOMAIN)


def _secret() -> bytes:
    try:
        return st.secrets["auth"]["signing_key"].encode()
    except (KeyError, FileNotFoundError) as e:
        raise RuntimeError(
            "Missing [auth].signing_key in .streamlit/secrets.toml. "
            "Copy .streamlit/secrets.toml.example and fill it in."
        ) from e


def _b64encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_token(email: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    email = email.strip().lower()
    if not is_allowed(email):
        raise ValueError(f"Refusing to issue token for non-{ALLOWED_DOMAIN} email")
    payload = {"email": email, "exp": int(time.time()) + ttl}
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64encode(sig)}"


def verify_token(token: str | None) -> str | None:
    """Return the email if the token is valid + allowed, else None."""
    if not token or "." not in token:
        return None
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64decode(sig), expected):
            return None
        payload = json.loads(_b64decode(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        email = str(payload.get("email", "")).lower()
        return email if is_allowed(email) else None
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def build_magic_link(base_url: str, token: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}?token={urllib.parse.quote(token)}"


def send_magic_email(to: str, link: str) -> tuple[bool, str]:
    """Send the magic link via SMTP. In dev mode, print to console instead.

    Returns (delivered, mode_label).
    """
    cfg = st.secrets.get("smtp", {})
    if not cfg or cfg.get("dev_print_only", False):
        print("\n" + "=" * 60)
        print(f"DEV MAGIC LINK for {to}")
        print(link)
        print("=" * 60 + "\n", flush=True)
        return True, "console"

    msg = EmailMessage()
    msg["Subject"] = "Sign in to the AccessRP Dashboard"
    msg["From"] = cfg["from"]
    msg["To"] = to
    msg.set_content(
        "Hello,\n\n"
        "Click the link below to sign in to the AccessRP dashboard. "
        "The link expires in 15 minutes.\n\n"
        f"{link}\n\n"
        "If you didn't request this, ignore this email.\n"
    )
    host, port = cfg["host"], int(cfg.get("port", 465))
    ctx = ssl.create_default_context()
    if cfg.get("use_ssl", True):
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as srv:
            srv.login(cfg["user"], cfg["password"])
            srv.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as srv:
            srv.starttls(context=ctx)
            srv.login(cfg["user"], cfg["password"])
            srv.send_message(msg)
    return True, "email"
