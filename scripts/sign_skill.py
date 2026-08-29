"""
Sign a skill's manifest with an Ed25519 key.

This is the authoring side of the supply-chain provenance (AST02 REQ-09): it writes
`signature` and `sign_public_key_id` into a skill's manifest.json, binding the
skill's canonical digest to a publisher key. The verification side is in
app/skills/manifest.py: a signature is honoured only when its key id appears in the
deployment's backend/policy/trusted_keys.json.

Usage:

  # Generate a fresh keypair (print the public key, keep the seed):
  python scripts/sign_skill.py --generate ./some/skill_folder

  # Sign a skill with an existing seed:
  python scripts/sign_skill.py ./some/skill_folder --key-seed <64-hex> --key-id lab-signing-key

The public key from --generate (or derived from --key-seed) is what an operator pastes
into trusted_keys.json to make that signing key trusted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.skills import signing

PRIVATE_SEED_HEX = 64


def _sign(manifest_path: Path, seed_hex: str, key_id: str) -> None:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = raw.get("digest")
    if not isinstance(digest, str):
        raise SystemExit(f"{manifest_path} has no 'digest' to sign; write one first.")

    raw["signature"] = signing.sign_digest(seed_hex, digest)
    raw["sign_public_key_id"] = key_id
    manifest_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    print(f"Signed digest {digest[:16]}... with key '{key_id}'; public key = "
          f"{signing.public_key_hex(seed_hex)}")


def _generate(key_id: str) -> None:
    seed_hex = signing.new_private_seed_hex()
    print("Generated a fresh key. Add this public key to trusted_keys.json:")
    print(f'  "{key_id}": "{signing.public_key_hex(seed_hex)}"')
    print(f"Use --key-seed {seed_hex} --key-id {key_id} to sign.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_dir", type=Path, help="skill folder containing manifest.json")
    parser.add_argument(
        "--generate", action="store_true",
        help="generate a fresh keypair and print the public key for trusted_keys.json",
    )
    parser.add_argument("--key-seed", type=str, help="64-hex Ed25519 private seed to sign with")
    parser.add_argument("--key-id", type=str, help="the sign_public_key_id to write")
    args = parser.parse_args()

    manifest_path = Path(args.skill_dir) / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"No manifest at {manifest_path}.")

    key_id = args.key_id or "lab-signing-key"

    if args.generate:
        _generate(key_id)
        return

    if not args.key_seed or len(args.key_seed) != PRIVATE_SEED_HEX:
        raise SystemExit("--key-seed is required (64 hex characters of the private seed).")

    _sign(manifest_path, args.key_seed, key_id)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
