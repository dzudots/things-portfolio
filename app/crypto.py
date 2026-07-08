"""
Field-level encryption for private user portfolio data.

Design goals (privacy-first, not a surveillance / tax product):
- Encrypt at rest: purchase price, override, notes, optional display name.
- Never store INN, passport, VIN, serial numbers as structured fields.
- Market comps stay global aggregates (not tied to a person).
- Server key encrypts blobs; only the owning account can read via app session.

This is application-level encryption (AES via Fernet). It protects against
casual DB leaks and makes clear that portfolio numbers are confidential
personal notes — not a public registry and not a tax filing channel.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import DATA_ENCRYPTION_KEY, SECRET_KEY

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    raw = (DATA_ENCRYPTION_KEY or "").strip()
    if raw:
        try:
            return Fernet(raw.encode("utf-8"))
        except Exception:
            logger.warning("Invalid THINGS_DATA_KEY — falling back to derived key")
    digest = hashlib.sha256(f"things-data:{SECRET_KEY}".encode("utf-8")).digest()
    derived = base64.urlsafe_b64encode(digest)
    if not DATA_ENCRYPTION_KEY:
        logger.warning(
            "THINGS_DATA_KEY not set — using key derived from SECRET_KEY. "
            "Set THINGS_DATA_KEY in production."
        )
    return Fernet(derived)


def encrypt_text(plain: Optional[str]) -> str:
    if plain is None or plain == "":
        return ""
    if plain.startswith(ENC_PREFIX):
        return plain
    token = _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")
    return ENC_PREFIX + token


def decrypt_text(stored: Optional[str]) -> str:
    if not stored:
        return ""
    if not stored.startswith(ENC_PREFIX):
        # Legacy plaintext (pre-encryption) — return as-is
        return stored
    token = stored[len(ENC_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt field — wrong THINGS_DATA_KEY?")
        return ""


def encrypt_float(value: Optional[float]) -> str:
    if value is None:
        return ""
    return encrypt_text(repr(float(value)))


def decrypt_float(stored: Optional[str]) -> Optional[float]:
    text = decrypt_text(stored)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def hash_email(email: str) -> str:
    """Lookup hash so we can avoid storing email in analytics joins unnecessarily."""
    normalized = email.lower().strip()
    return hashlib.sha256(f"things-email:{normalized}".encode("utf-8")).hexdigest()
