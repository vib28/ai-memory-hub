from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .utils import one_line

# ---------------------------------------------------------------------------
# Vault encryption at rest (AES-256-GCM)
# ---------------------------------------------------------------------------

# Magic bytes prefix so we can detect encrypted files on disk.
VAULT_ENCRYPTED_MAGIC = b"AMHENC\x00\x01"

# Number of random bytes used as the per-file nonce for AES-256-GCM.
NONCE_LENGTH = 12


class VaultEncryptionError(Exception):
    """Raised when vault encryption or decryption fails."""


def _resolve_key(base64_key: str) -> bytes:
    """Decode a base64-encoded 32-byte key, raising a clear error on misuse."""
    try:
        raw = base64.b64decode(base64_key, validate=True)
    except Exception as exc:
        raise VaultEncryptionError(
            "VAULT_ENCRYPTION_KEY is not valid base64"
        ) from exc
    if len(raw) != 32:
        raise VaultEncryptionError(
            f"VAULT_ENCRYPTION_KEY must decode to 32 bytes (got {len(raw)})"
        )
    return raw


def generate_encryption_key() -> str:
    """Generate a fresh 256-bit key, returned as a base64-encoded string."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


def encrypt_data(plaintext: bytes | str, base64_key: str) -> bytes:
    """Encrypt ``plaintext`` with AES-256-GCM using the given base64 key.

    Returns bytes with the layout::

        VAULT_ENCRYPTED_MAGIC || nonce (12 bytes) || ciphertext+tag

    The nonce is randomly generated per call and never reused.
    """
    key_bytes = _resolve_key(base64_key)
    nonce = os.urandom(NONCE_LENGTH)
    aesgcm = AESGCM(key_bytes)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext, None)
    return VAULT_ENCRYPTED_MAGIC + nonce + ciphertext


def decrypt_data(blob: bytes, base64_key: str) -> bytes:
    """Decrypt a blob produced by :func:`encrypt_data`, returning plaintext bytes.

    Raises :class:`VaultEncryptionError` if the magic bytes are missing or the
    authentication tag fails to verify (wrong key, truncated file, tampering).
    """
    if not blob.startswith(VAULT_ENCRYPTED_MAGIC):
        raise VaultEncryptionError("data does not start with the vault encryption magic header")
    key_bytes = _resolve_key(base64_key)
    nonce = blob[len(VAULT_ENCRYPTED_MAGIC): len(VAULT_ENCRYPTED_MAGIC) + NONCE_LENGTH]
    ciphertext = blob[len(VAULT_ENCRYPTED_MAGIC) + NONCE_LENGTH:]
    aesgcm = AESGCM(key_bytes)
    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise VaultEncryptionError("decryption failed: wrong key or corrupted data") from exc


def is_encrypted_blob(blob: bytes) -> bool:
    """Return True if ``blob`` looks like an encrypted vault file."""
    return blob.startswith(VAULT_ENCRYPTED_MAGIC)


class VaultEncryption:
    """Transparent file-level encryption wrapper for vault files.

    Any code path that reads or writes a vault file (``.md``) can use this
    class to automatically encrypt on write and decrypt on read when a key is
    configured. When no key is set, the class is a no-op passthrough so the
    caller code works unchanged regardless of whether encryption is active.

    Parameters
    ----------
    key:
        The encryption key as a base64-encoded 32-byte string, or an empty
        string to disable encryption.
    """

    def __init__(self, key: str) -> None:
        self._key: str = key if key else ""
        self._enabled: bool = bool(self._key)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def encrypt_file(self, path: Path, content: str) -> None:
        """Write ``content`` to ``path`` -- encrypting if encryption is enabled.

        When enabled the on-disk file gets a ``.enc`` extension (so callers
        using a plain ``.md`` path will still work transparently via
        :meth:`read_file`).
        """
        if self._enabled:
            blob = encrypt_data(content, self._key)
            enc_path = path.with_suffix(path.suffix + ".enc")
            enc_path.write_bytes(blob)
        else:
            path.write_text(content, encoding="utf-8")

    def read_file(self, path: Path) -> str:
        """Read and return plaintext from ``path``.

        If the ``.enc`` companion exists it is decrypted; otherwise the plain
        ``.md`` file is read. When encryption is disabled this simply reads
        ``path`` as UTF-8 text.
        """
        if self._enabled:
            enc_path = path.with_suffix(path.suffix + ".enc")
            if enc_path.exists():
                blob = enc_path.read_bytes()
                return decrypt_data(blob, self._key).decode("utf-8")
        return path.read_text(encoding="utf-8")

    def delete_file(self, path: Path) -> None:
        """Remove both the plain and encrypted form if present."""
        enc_path = path.with_suffix(path.suffix + ".enc")
        for p in (enc_path, path):
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    def plaintext_path(self, path: Path) -> Path:
        """Return the on-disk path holding the (possibly encrypted) file content."""
        if self._enabled:
            enc_path = path.with_suffix(path.suffix + ".enc")
            if enc_path.exists():
                return enc_path
        return path

    def encrypted_path(self, path: Path) -> Path:
        """Return the ``.enc`` companion path for ``path``."""
        return path.with_suffix(path.suffix + ".enc")

    def file_exists(self, path: Path) -> bool:
        """Return True if either the plaintext or encrypted form exists."""
        if self._enabled and path.with_suffix(path.suffix + ".enc").exists():
            return True
        return path.exists()


def get_vault_encryption(vault_root: Optional[Path] = None) -> VaultEncryption:
    """Return a :class:`VaultEncryption` configured from the environment.

    Reads ``VAULT_ENCRYPTION_KEY`` from ``os.environ``. Returns a no-op
    instance when the key is not set or empty.
    """
    key = os.environ.get("VAULT_ENCRYPTION_KEY", "")
    return VaultEncryption(key)


# ---------------------------------------------------------------------------
# PII / secret detection (unchanged from the original security.py)
# ---------------------------------------------------------------------------

@dataclass
class SecurityResult:
    safe: bool
    reason: str = ""

SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", re.I), "private key"),
    (re.compile(r"\b(?:api[_ -]?key|secret[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd)\b\s*[=:]\s*\S+", re.I), "credential assignment"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "API-style secret"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"\b(?:seed phrase|mnemonic)\b\s*[=:]\s*(?:[a-z]+\s+){7,}[a-z]+", re.I), "seed phrase"),
]

HIGH_RISK_LABELS = re.compile(
    r"\b(?:aadhaar|aadhar|pan number|passport number|bank account|routing number|cvv|pin code for account)\b",
    re.I,
)

# Candidate payment-card-shaped runs: 13-19 digits, optionally split by spaces or
# hyphens only every 4 digits (real card formatting), never at arbitrary offsets.
# This alone still matches plenty of non-card numbers (IDs, ranges), so a Luhn
# check below decides -- real card numbers pass it, and an arbitrary digit run
# has only ~1-in-10 odds of doing so (issue #4).
_CARD_CANDIDATE_RE = re.compile(r"\b\d{4}(?:[ -]?\d{4}){2,3}(?:[ -]?\d{1,3})?\b")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _looks_like_card(text: str) -> bool:
    for m in _CARD_CANDIDATE_RE.finditer(text):
        digits = re.sub(r"[ -]", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            return True
    return False


def check_text(text: str) -> SecurityResult:
    # Normalize once before any regex matching: collapse internal whitespace
    # and strip leading/trailing whitespace. This ensures patterns written
    # against clean input match even when callers pass verbose formatting.
    t = one_line(text)
    if not t:
        return SecurityResult(False, "empty memory")
    if len(t) > 1500:
        return SecurityResult(False, "memory is too long; store a durable compressed fact instead")
    for pattern, label in SECRET_PATTERNS:
        if pattern.search(t):
            return SecurityResult(False, f"probable sensitive data detected: {label}")
    if _looks_like_card(t):
        return SecurityResult(False, "probable sensitive data detected: possible payment/account number")
    if HIGH_RISK_LABELS.search(t):
        return SecurityResult(False, "probable sensitive identifier")
    return SecurityResult(True, "")
