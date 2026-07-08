"""Tests for field-level encryption of private portfolio data."""

from __future__ import annotations

import unittest

from app.crypto import decrypt_float, decrypt_text, encrypt_float, encrypt_text


class CryptoTests(unittest.TestCase):
    def test_roundtrip_text(self):
        enc = encrypt_text("личная заметка")
        self.assertTrue(enc.startswith("enc:v1:"))
        self.assertEqual(decrypt_text(enc), "личная заметка")

    def test_roundtrip_float(self):
        enc = encrypt_float(65000.5)
        self.assertTrue(enc.startswith("enc:v1:"))
        self.assertEqual(decrypt_float(enc), 65000.5)

    def test_none_float(self):
        self.assertEqual(encrypt_float(None), "")
        self.assertIsNone(decrypt_float(""))

    def test_legacy_plaintext(self):
        self.assertEqual(decrypt_text("plain"), "plain")


if __name__ == "__main__":
    unittest.main()
