# -*- coding: utf-8 -*-
"""The AES envelope required by the BENEFIT Payment Gateway.

Every parameter below is fixed by BENEFIT. None of it is our choice:

    AES / CBC / PKCS5Padding
    key : the Terminal Resource Key, used as raw UTF-8 bytes (32 chars -> AES-256)
    IV  : the literal ASCII string "PGKEYENCDECIVSPC"
    wire: uppercase hexadecimal

The step that is easy to miss, and that the guide states twice: the plaintext is
URL-encoded *before* encryption and URL-decoded *after* decryption. Skip it and the
gateway answers IPAY0100013 "Invalid transaction data" with no further explanation.

A hard-coded IV is weak by modern standards. It is mandated by the gateway, so it
stays. Note it in a security review rather than "fixing" it here -- changing it breaks
every transaction.

Reference: BENEFIT Payment Gateway Integration Guide v1.4, sections 4.2 - 4.4.
See Documentation/payments/benefit_gateway.md section 3.
"""
from __future__ import unicode_literals

import binascii

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from six import text_type
from six.moves.urllib.parse import quote_plus, unquote_plus

# Fixed by BENEFIT. Do not parameterise.
BENEFIT_IV = b"PGKEYENCDECIVSPC"

# AES block size in bits, for PKCS7. "PKCS5Padding" in the Java sample is the same
# thing at this block size -- Java simply uses the older name.
_BLOCK_BITS = 128

_VALID_KEY_LENGTHS = (16, 24, 32)


def _key_bytes(key):
	"""Validate the resource key and return it as bytes.

	Fail loudly here. A wrong-length key otherwise surfaces as an opaque gateway
	error much later, after a customer has already been redirected.
	"""
	if not key:
		raise ValueError("BENEFIT resource key is empty")

	if isinstance(key, text_type):
		key = key.encode("utf-8")

	if len(key) not in _VALID_KEY_LENGTHS:
		raise ValueError(
			"BENEFIT resource key must be 16, 24 or 32 bytes for AES; got {0}".format(len(key))
		)

	return key


def _cipher(key):
	return Cipher(
		algorithms.AES(_key_bytes(key)),
		modes.CBC(BENEFIT_IV),
		backend=default_backend(),
	)


def encrypt(key, plaintext):
	"""URL-encode, AES-encrypt, and return uppercase hex.

	:param key: the Terminal Resource Key
	:param plaintext: the JSON string to send as ``trandata``
	"""
	encoded = quote_plus(plaintext)

	padder = padding.PKCS7(_BLOCK_BITS).padder()
	data = padder.update(encoded.encode("utf-8")) + padder.finalize()

	encryptor = _cipher(key).encryptor()
	ciphertext = encryptor.update(data) + encryptor.finalize()

	return binascii.hexlify(ciphertext).decode("ascii").upper()


def decrypt(key, ciphertext_hex):
	"""Reverse of :func:`encrypt` -- hex in, decoded plaintext out."""
	if not ciphertext_hex:
		raise ValueError("empty trandata")

	raw = binascii.unhexlify(ciphertext_hex.strip())

	decryptor = _cipher(key).decryptor()
	padded = decryptor.update(raw) + decryptor.finalize()

	unpadder = padding.PKCS7(_BLOCK_BITS).unpadder()
	plain = unpadder.update(padded) + unpadder.finalize()

	return unquote_plus(plain.decode("utf-8"))
