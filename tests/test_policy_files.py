"""
Checks for the policy-file loader (app/skills/policy_files.py).

These files (skill allowlist, revocations, trusted keys) are the advisory policy
added by the AST02 supply-chain work. The properties under test:

  - a missing or unreadable file yields the caller's fallback rather than crashing;
  - an existing, well-formed file is read back exactly;
  - the string-set helper parses both plain lists and object-under-a-key shapes.

Covers: AST02 spec REQ-06, REQ-08, REQ-09; implementation plan T-02.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.skills.policy_files import load_json_policy, load_key_set, load_string_set


def make_settings(policy_dir: Path) -> SimpleNamespace:
    """A minimal settings stand-in that only exposes the policy folder."""
    return SimpleNamespace(policy_dir=policy_dir)


def test_loader_returns_fallback_for_missing_file(tmp_path):
    """A file that is not there is 'not present', and the fallback is returned."""
    settings = make_settings(tmp_path)

    result = load_json_policy(settings, "missing.json", fallback={"defaults": []})

    assert result == {"defaults": []}


def test_loader_reads_existing_policy_file(tmp_path):
    """A well-formed file is read back as its parsed content."""
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "allowlist.json").write_text(
        json.dumps(["task_summary", "standup_sync"]), encoding="utf-8"
    )
    settings = make_settings(policy_dir)

    result = load_json_policy(settings, "allowlist.json", fallback=[])

    assert result == ["task_summary", "standup_sync"]


def test_string_set_parse(tmp_path):
    """The string-set helper handles both a plain list and a list under a key."""
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "plain.json").write_text(json.dumps(["a", "b", "a"]), encoding="utf-8")
    (policy_dir / "grouped.json").write_text(
        json.dumps({"digests": ["abc"], "publishers": ["Northwind"]}), encoding="utf-8"
    )
    settings = make_settings(policy_dir)

    plain = load_string_set(settings, "plain.json", fallback=[])
    grouped = load_string_set(settings, "grouped.json", field="publishers", fallback=[])

    assert plain == {"a", "b"}
    assert grouped == {"Northwind"}


def test_string_set_returns_fallback_when_field_absent(tmp_path):
    """An object file without the requested key yields the fallback, not a crash."""
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "empty.json").write_text(json.dumps({"digests": []}), encoding="utf-8")
    settings = make_settings(policy_dir)

    result = load_string_set(settings, "empty.json", field="publishers", fallback={"x"})

    assert result == {"x"}


def test_key_set_parses_id_to_key_map(tmp_path):
    """The trusted-keys file is read as an id -> key map."""
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "trusted_keys.json").write_text(
        json.dumps({"key-1": "AAAA", "key-2": "BBBB"}), encoding="utf-8"
    )
    settings = make_settings(policy_dir)

    keys = load_key_set(settings, "trusted_keys.json")

    assert keys == {"key-1": "AAAA", "key-2": "BBBB"}
