"""
Canonical content digests for skills.

The point of a digest here is to let TaskBot notice when a skill's files change
after they were vetted. Two digests are provided:

  resource_digest(paths)     - a stable sha256 over the bytes of a set of files;
  canonical_digest(...)      - a digest that binds a manifest object to the bytes
                               of its resource files, in one value.

Everything that verifies skill content (checksums, signatures, revocations) uses
these two functions and no other digest, so there is exactly one definition of
"is this the skill we vetted?" in the whole app.

Canonicalisation rules:

  - The manifest object is serialised with sorted keys and no extra whitespace
    (json.dumps(sort_keys=True, separators=(",", ":"))), so two manifests that mean
    the same thing produce the same bytes regardless of the order their keys were
    typed.
  - Provenance fields that are records ABOUT the artifact - the digest itself, the
    digest algorithm, and any signature - are excluded from the hash, because an
    artifact's identity cannot sensibly include a checksum of that same identity.
  - Each resource file contributes the sha256 of its raw bytes, in the order the
    paths are given, so the folder layout the skill declared is part of what is
    bound.

Specification references: AST02 supply-chain spec REQ-02 and REQ-09; implementation
plan T-01.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

# Keys that describe provenance about the artifact rather than its content. They are
# never part of what is hashed, or a manifest could not carry its own digest without
# changing that digest (a circular definition).
_EXCLUDED_KEYS = frozenset({"digest", "digest_alg", "signature", "sign_public_key_id"})


def sha256_hex(data: bytes) -> str:
    """The hex sha256 of some bytes - the ordinary building block used below."""
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    """
    The hex sha256 of one file's raw bytes.

    In: the path. Out: the hex digest. Reading is done in bounded chunks so a very
    large resource does not load the whole thing into memory at once.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resource_digest(paths: Sequence[Path]) -> str:
    """
    A stable sha256 over a declared set of files.

    In: the file paths, in the order they are declared.
    Out: a single hex digest covering all of them together.

    Each file contributes the sha256 of its bytes, in order, so the digest changes
    if any file changes OR if the ordering of the set changes.
    """
    merged = hashlib.sha256()
    for path in paths:
        merged.update(file_sha256(Path(path)).encode("utf-8"))
    return merged.hexdigest()


def canonical_json(manifest: dict) -> str:
    """
    The canonical JSON text of a manifest object.

    In: the manifest as a dict. Out: its serialisation with sorted keys, with the
    provenance fields excluded. Used so two semantically-identical manifests hash
    the same and so a manifest can carry its own digest without circularity.
    """
    body = {key: value for key, value in manifest.items() if key not in _EXCLUDED_KEYS}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_digest(manifest: dict, resource_paths: Sequence[Path]) -> str:
    """
    The canonical digest that binds a manifest to its resource files.

    In: the manifest as a dict, and the ordered list of resource file paths.
    Out: a hex sha256 covering both the manifest object and the resource bytes.

    The manifest contributes its canonical JSON text (see canonical_json); each
    resource contributes the sha256 of its raw bytes, in the order the paths are
    given. Changing any resource, or reordering the resources, changes the result.
    """
    content = canonical_json(manifest).encode("utf-8")
    for path in resource_paths:
        content += file_sha256(Path(path)).encode("utf-8")
    return hashlib.sha256(content).hexdigest()
