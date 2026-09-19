from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_hub.security import (
    VAULT_ENCRYPTED_MAGIC,
    VaultEncryption,
    VaultEncryptionError,
    decrypt_data,
    encrypt_data,
    generate_encryption_key,
    get_vault_encryption,
    is_encrypted_blob,
)


class AES256GCMTests(unittest.TestCase):
    def setUp(self):
        self.key = generate_encryption_key()

    def test_generate_key_is_base64_32_bytes(self):
        raw = base64.b64decode(self.key)
        assert len(raw) == 32

    def test_encrypt_then_decrypt_round_trip(self):
        plaintext = "hello world, secret memory"
        blob = encrypt_data(plaintext, self.key)
        assert blob.startswith(VAULT_ENCRYPTED_MAGIC)
        assert blob != plaintext.encode()
        decrypted = decrypt_data(blob, self.key).decode("utf-8")
        assert decrypted == plaintext

    def test_encrypt_bytes_input(self):
        blob = encrypt_data(b"raw bytes", self.key)
        assert decrypt_data(blob, self.key) == b"raw bytes"

    def test_encrypt_produces_different_ciphertext_each_time(self):
        """AES-GCM nonces must be unique per call."""
        a = encrypt_data("same text", self.key)
        b = encrypt_data("same text", self.key)
        assert a != b
        # But both decrypt to the same plaintext
        assert decrypt_data(a, self.key) == decrypt_data(b, self.key)

    def test_decrypt_with_wrong_key_raises(self):
        blob = encrypt_data("secret", self.key)
        other_key = generate_encryption_key()
        with pytest.raises(VaultEncryptionError):
            decrypt_data(blob, other_key)

    def test_decrypt_corrupted_blob_raises(self):
        blob = encrypt_data("secret", self.key)
        corrupted = blob[:-1]  # truncate
        with pytest.raises(VaultEncryptionError):
            decrypt_data(corrupted, self.key)

    def test_decrypt_without_magic_header_raises(self):
        with pytest.raises(VaultEncryptionError) as ctx:
            decrypt_data(b"not encrypted data", self.key)
        assert "magic" in str(ctx.value).lower()

    def test_invalid_base64_key_raises(self):
        with pytest.raises(VaultEncryptionError):
            encrypt_data("x", "not-base64-!!!")

    def test_wrong_length_key_raises(self):
        short = base64.b64encode(b"only-16-bytes").decode()
        with pytest.raises(VaultEncryptionError) as ctx:
            encrypt_data("x", short)
        assert "32" in str(ctx.value)

    def test_is_encrypted_blob(self):
        assert is_encrypted_blob(encrypt_data("hi", self.key))
        assert not is_encrypted_blob(b"plain text")


class VaultEncryptionFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.key = generate_encryption_key()

    def tearDown(self):
        self.tmp.cleanup()

    def test_encrypt_file_writes_dot_enc(self):
        ve = VaultEncryption(self.key)
        path = self.dir / "mem.md"
        ve.encrypt_file(path, "secret content")
        enc = self.dir / "mem.md.enc"
        assert enc.exists()
        assert not path.exists()  # plaintext not written when enc enabled
        assert is_encrypted_blob(enc.read_bytes())

    def test_read_file_decrypts(self):
        ve = VaultEncryption(self.key)
        path = self.dir / "mem.md"
        ve.encrypt_file(path, "my plaintext")
        assert ve.read_file(path) == "my plaintext"

    def test_plain_path_when_encrypted_exists(self):
        ve = VaultEncryption(self.key)
        path = self.dir / "mem.md"
        ve.encrypt_file(path, "x")
        assert ve.encrypted_path(path) == self.dir / "mem.md.enc"

    def test_no_op_when_key_empty(self):
        ve = VaultEncryption("")
        assert not ve.enabled
        path = self.dir / "mem.md"
        ve.encrypt_file(path, "plain")
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "plain"
        assert ve.read_file(path) == "plain"

    def test_file_exists_detects_enc(self):
        ve = VaultEncryption(self.key)
        path = self.dir / "mem.md"
        ve.encrypt_file(path, "x")
        assert ve.file_exists(path)
        assert not (self.dir / "missing.md").exists()
        ve2 = VaultEncryption("")
        # with enc disabled, file_exists just checks the plaintext
        assert not ve2.file_exists(path)

    def test_delete_both_forms(self):
        ve = VaultEncryption(self.key)
        path = self.dir / "mem.md"
        ve.encrypt_file(path, "x")
        assert ve.encrypted_path(path).exists()
        ve.delete_file(path)
        assert not ve.encrypted_path(path).exists()

    def test_decrypt_wrong_key_file_raises(self):
        ve_a = VaultEncryption(self.key)
        path = self.dir / "mem.md"
        ve_a.encrypt_file(path, "secret")
        ve_b = VaultEncryption(generate_encryption_key())
        with pytest.raises(VaultEncryptionError):
            ve_b.read_file(path)


class GetVaultEncryptionTests(unittest.TestCase):
    def test_returns_noop_when_env_unset(self):
        os.environ.pop("VAULT_ENCRYPTION_KEY", None)
        ve = get_vault_encryption()
        assert not ve.enabled

    def test_returns_enabled_when_env_set(self):
        key = generate_encryption_key()
        with patch.dict(os.environ, {"VAULT_ENCRYPTION_KEY": key}):
            ve = get_vault_encryption()
            assert ve.enabled


if __name__ == "__main__":
    unittest.main()
