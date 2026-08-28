"""
Loading the small JSON policy files the supply-chain checks rely on.

Three files (allowlist, revocations, trusted keys) are read from the shared policy
folder. They are all *optional*: until adopted, they hold empty lists, and a missing
file is not an error - each callers hands in the fallback to use instead. This keeps
the lab runnable before any of the lists are populated.

The vocabulary and baseline files are NOT loaded here; they are mandatory core policy
that the app already loads elsewhere (app/skills/manifest.py). These three are the
new, advisory ADDITIONS introduced by the AST02 supply-chain work.

Specification references: AST02 spec REQ-06, REQ-08, REQ-09; implementation plan T-02.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path


def _policy_file(settings, filename: str) -> Path:
    """The on-disk path of one policy file in the shared policy folder."""
    return Path(settings.policy_dir) / filename


def load_json_policy(settings, filename: str, fallback):
    """
    Read one JSON policy file, returning a fallback if it cannot be read.

    In: the settings (for their policy folder), the file name, and the value to use
    if the file is missing, unreadable, or not valid JSON.
    Out: the parsed content, or `fallback`.

    Missing or broken policy files never crash the app. The allowlist, revocation
    and key files are advisory; an unreadable one is treated as "not present" and
    the caller's fallback (usually an empty list) takes over.
    """
    path = _policy_file(settings, filename)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return raw


def _as_strings(value, filename: str) -> list[str]:
    """Coerce a parsed policy value into a list of non-empty strings, if it can be."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if item]
    raise ValueError(f"{filename} must be a list of strings.")


def load_string_set(
    settings,
    filename: str,
    *,
    field: str | None = None,
    fallback: Sequence[str] = (),
) -> set[str]:
    """
    Load a set of strings (skill ids, publisher names, digests) from a policy file.

    In:
      settings - for the policy folder;
      filename - which file;
      field    - if the file is an object, the key whose value is the string list;
                 if None, the whole file is expected to be a list of strings;
      fallback - what to use when the file is missing or unreadable.
    Out: the strings as a set.

    A malformed value is not silently accepted: if the file parses as JSON but does
    not hold a usable list of strings, we raise rather than guess, because quietly
    trusting a badly-shaped allowlist/revocation file would be the opposite of the
    safety this whole feature exists to provide.
    """
    raw = load_json_policy(settings, filename, None)
    if raw is None:
        return set(fallback)

    if field is not None:
        if not isinstance(raw, Mapping) or field not in raw:
            return set(fallback)
        value = raw[field]
    else:
        value = raw

    try:
        return set(_as_strings(value, filename))
    except ValueError:
        raise ValueError(
            f"Policy file {filename!r} must hold a list of strings, got: {value!r}."
        ) from None


def load_key_set(
    settings,
    filename: str,
    *,
    fallback: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """
    Load the map of public keys (key id -> key material) from a policy file.

    In:
      settings - for the policy folder;
      filename - which file;
      fallback - what to use when the file is missing or unreadable.
    Out: the keys as a dict of id -> key string.

    The trusted-keys file is an object whose keys are identifiers and whose values
    are the public keys. A non-object value makes verification impossible to reason
    about, so it raises rather than returning something unusable.
    """
    raw = load_json_policy(settings, filename, None)
    if raw is None:
        return dict(fallback or {})

    if not isinstance(raw, Mapping):
        raise ValueError(
            f"Policy file {filename!r} must be an object of 'id -> key' pairs."
        )

    result: dict[str, str] = {}
    for key_id, key in raw.items():
        if isinstance(key, str) and key:
            result[str(key_id)] = key
    return result
