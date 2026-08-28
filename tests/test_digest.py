"""
Checks for the canonical content-digest helpers (app/skills/digest.py).

These are the single definition of "is this the skill we vetted?", used later by
content verification at install and run (REQ-02), and by signatures over skill
content (REQ-09). Three properties are the load-bearing ones:

  - the digest is stable: the same content gives the same hash, no matter the
    order the manifest's keys were written in;
  - the digest changes when any resource file changes;
  - a digest over the resource set is a real sha256.

Covers: AST02 spec REQ-02, REQ-09; implementation plan T-01.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.skills.digest import canonical_digest, resource_digest


MANIFEST = {
    "id": "example_skill",
    "name": "Example",
    "version": "1.0.0",
    "author": "TaskBot Labs",
    "entrypoint": "skill.py:run",
}


def _write_resources(folder: Path) -> tuple[Path, Path]:
    """A manifest file and a code file, written to disk."""
    manifest_path = folder / "manifest.json"
    manifest_path.write_text(json.dumps(MANIFEST), encoding="utf-8")
    code_path = folder / "skill.py"
    code_path.write_text("def run(ctx, params):\n    pass\n", encoding="utf-8")
    return manifest_path, code_path


def test_canonical_digest_is_stable_across_key_order(tmp_path):
    """Two manifests meaning the same thing hash the same, whatever key order."""
    folder = tmp_path / "folder"
    folder.mkdir()
    manifest_path, code_path = _write_resources(folder)

    shuffled = dict(reversed(list(MANIFEST.items())))
    assert set(shuffled.items()) == set(MANIFEST.items())

    first = canonical_digest(MANIFEST, [manifest_path, code_path])
    second = canonical_digest(shuffled, [manifest_path, code_path])

    assert first == second


def test_canonical_digest_changes_when_a_resource_changes(tmp_path):
    """Editing a resource file must produce a different digest."""
    folder = tmp_path / "folder"
    folder.mkdir()
    manifest_path, code_path = _write_resources(folder)

    before = canonical_digest(MANIFEST, [manifest_path, code_path])

    code_path.write_text("def run(ctx, params):\n    return 'changed'\n", encoding="utf-8")

    after = canonical_digest(MANIFEST, [manifest_path, code_path])

    assert before != after


def test_resource_digest_is_sha256_form(tmp_path):
    """The resource-set digest is a normal sha256: 64 lowercase hex characters."""
    folder = tmp_path / "folder"
    folder.mkdir()
    code_path = folder / "skill.py"
    code_path.write_text("def run(ctx, params):\n    pass\n", encoding="utf-8")

    digest = resource_digest([code_path])

    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")
