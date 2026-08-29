"""
Ed25519 signing support for skill provenance.

Skills may carry a signature over their canonical digest: `signature` (a 64-byte
Ed25519 signature as 128 hex characters) plus `sign_public_key_id` naming which
publisher key signed it. The app verifies that signature only when it actually
trusts the named key (a key listed in the shared `trusted_keys.json` policy file).

This module owns the crypto primitives and the shared-trust public-key loader. The
decision of WHEN to require a signature lives in app/skills/manifest.py, alongside
the manifest checks; this file deliberately does not know anything about settings or
the manifest format beyond the digest bytes it is asked to sign.

Specification references: AST02 supply-chain spec REQ-09; implementation plan T-09.
"""

from __future__ import annotations

import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def _message_for(digest: str) -> bytes:
    """The exact bytes a signature binds: the canonical digest as UTF-8 text."""
    return digest.encode("utf-8")


def sign_digest(private_key_hex: str, digest: str) -> str:
    """
    Sign a canonical digest with an Ed25519 private key.

    In: the 32-byte private key seed as 64 hex characters, and the hex digest.
    Out: the signature as 128 hex characters.

    The message signed is the digest text itself, so a signature only ever vouches
    for a specific content digest - never for an arbitrary manifest body.
    """
    key = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    return key.sign(_message_for(digest)).hex()


def public_key_hex(private_key_hex: str) -> str:
    """
    The 32-byte public key (as 64 hex chars) matching an Ed25519 private seed.

    In: the 64-hex private seed. Out: the corresponding 64-hex public key.
    """
    key = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()


def new_private_seed_hex() -> str:
    """A fresh random 64-hex Ed25519 private seed (for generating signing keys)."""
    return ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    ).hex()


def verify_signature(public_key_hex: str, signature_hex: str, digest: str) -> bool:
    """
    Check a signature against the public key and digest it claims to cover.

    In: the 32-byte public key as 64 hex characters, the signature as 128 hex
    characters, and the canonical digest.
    Out: True only if the signature is valid for that key and digest.

    A malformed key or signature is treated as a failed check, never an error.
    """
    try:
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(public_key_hex)
        )
        public_key.verify(bytes.fromhex(signature_hex), _message_for(digest))
        return True
    except (ValueError, InvalidSignature):
        return False


def load_trusted_keys(path: Path) -> dict[str, str]:
    """
    Read the shared trust store - a map of key id -> public key.

    In: the path to trusted_keys.json. Out: the map of id to public-key hex.

    Any problem here raises, because a silently-empty trust store would look like
    "no trusted keys" and quietly disable signature checks - the unsafe direction.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            "trusted_keys.json must be an object mapping key id to public key."
        )
    return {str(key): value for key, value in raw.items() if isinstance(value, str) and value}
