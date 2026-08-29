"""
Reading and checking a skill's description file (its "manifest").

Every skill is a folder holding two things:

  manifest.json - what the skill SAYS about itself: its name, what it does, and
                  which permissions it claims to need.
  skill.py      - what the skill ACTUALLY does when it runs.

Those two are written separately and on purpose. The gap between what something
claims and what it does is the whole subject of this security exercise - so the app
must never generate one from the other, and must always treat the claim as just a
claim.

This file only deals with the claim. Nothing here checks behaviour.

A note on failures: a manifest that will not parse makes the skill "invalid". That
is NOT a security finding. A skill that cannot run cannot misbehave, and a typo is
not an attack. Invalid skills are shown in the store with their problems listed so
the author can fix them.

Specification references: feature spec sections 3.3, 3.5 and 5.3; TDD section 2.2;
decision S-6.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import BaseModel, Field

from app.skills import signing

# A skill identifier must be lowercase letters, digits and underscores, starting
# with a letter, three to forty characters. It doubles as the name the AI model uses
# to ask for the skill, so it has to be simple and predictable.
SKILL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,39}$")

# The entrypoint says which file and which function to call, e.g. "skill.py:run".
ENTRYPOINT_PATTERN = re.compile(r"^[A-Za-z0-9_]+\.py:[A-Za-z_][A-Za-z0-9_]*$")

# A content digest is a plain lower-case hex sha256. The manifest carries the digest
# of its own content (see app/skills/digest.py); this is the format every committed
# manifest must satisfy (AST02 REQ-02).
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

# An Ed25519 signature is 64 bytes = 128 hex characters. A public key is 32 bytes =
# 64 hex characters. Both are provenance records about the skill, not content, so
# they are excluded from the canonical digest (see app/skills/digest.py).
SIGNATURE_HEX = re.compile(r"^[0-9a-f]{128}$")
PUBLIC_KEY_HEX = re.compile(r"^[0-9a-f]{64}$")


class CapabilityDeclaration(BaseModel):
    """
    One permission a skill claims to need.

    id     - which capability, from the shared vocabulary.
    scope  - the fine print: which files, which websites, which tasks.
    reason - the explanation shown to the user in the skill store.
    """

    id: str
    scope: list[str] = Field(default_factory=list)
    reason: str = ""


class Invocation(BaseModel):
    """
    How the AI model is told about this skill.

    when_to_use - plain wording describing the situations this skill fits.
    parameters  - a description of the values the model must supply, written in the
                  standard "JSON Schema" format.
    """

    when_to_use: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class Manifest(BaseModel):
    """Everything a skill claims about itself."""

    schema_version: int = 1
    id: str
    name: str
    version: str
    author: str
    category: str
    description: str
    invocation: Invocation
    capabilities: list[CapabilityDeclaration] = Field(default_factory=list)
    entrypoint: str
    # The canonical sha256 of the skill's own content (manifest + resource files),
    # computed with app/skills/digest.py. Required so every skill binds a checksum of
    # what it actually is, which is what lets the app notice tampering later (REQ-02).
    digest: str
    digest_alg: str = "sha256"
    # An optional Ed25519 signature (128 hex chars) binding the digest to a signing
    # key, and the id of that key (REQ-09). Excluded from the canonical digest.
    signature: str | None = None
    sign_public_key_id: str | None = None


class VocabularyEntry(BaseModel):
    """One capability from the shared vocabulary file."""

    id: str
    brokered: bool
    scope_kind: str
    description: str = ""


class Vocabulary:
    """
    The shared list of capabilities, loaded from the policy folder.

    Both sides of the security comparison use this same list - it is what makes a
    declaration and an observation directly comparable.
    """

    def __init__(self, entries: list[VocabularyEntry]) -> None:
        self._entries = {entry.id: entry for entry in entries}

    def get(self, capability_id: str) -> VocabularyEntry | None:
        """Look up one capability. Returns None if the name is not recognised."""
        return self._entries.get(capability_id)

    def ids(self) -> set[str]:
        """All known capability names."""
        return set(self._entries)

    def scope_kind(self, capability_id: str) -> str:
        """
        What sort of limits this capability uses (file path, website address...).

        Unknown capabilities report "none", which never matches anything - the safe
        answer when we do not understand what we are looking at.
        """
        entry = self.get(capability_id)
        return entry.scope_kind if entry else "none"


def load_vocabulary(path: Path) -> Vocabulary:
    """
    Load the shared capability list from disk.

    In: the path to capability_vocabulary.json.
    Out: a Vocabulary object.

    Any problem here raises an error and stops the app. That is deliberate: without
    this list the app cannot tell what a skill declared, so it would report no
    problems at all - which looks exactly like a clean result and would be a lie.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = [VocabularyEntry(**item) for item in raw["capabilities"]]
    return Vocabulary(entries)


def load_category_names(path: Path) -> set[str]:
    """
    Read just the list of category names from the baselines file.

    In: the path to capability_baselines.json. Out: the set of category names.

    Why this lives here rather than reusing the findings package: checking a
    manifest is allowed to know WHICH categories exist, but the skills side of the
    app must never import the findings side. That separation is a deliberate rule -
    it is what guarantees the part of the app that supervises a running skill cannot
    peek at what the skill declared. See TDD section 10.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return set(raw.get("categories", {}))


def _validate_capability(
    index: int,
    declaration: dict[str, Any],
    vocabulary: Vocabulary,
    errors: list[str],
) -> None:
    """
    Check one declared permission and add any problems to the errors list.

    In: its position in the list, the raw declaration, the vocabulary, and the list
    to add problems to. Out: nothing (problems are appended to `errors`).
    """
    where = f"capabilities[{index}]"

    capability_id = declaration.get("id")
    if not capability_id:
        errors.append(f"{where}: missing 'id'.")
        return

    if capability_id not in vocabulary.ids():
        errors.append(
            f"{where}: '{capability_id}' is not a known capability. "
            f"Known ones are: {', '.join(sorted(vocabulary.ids()))}."
        )
        return

    scope = declaration.get("scope")
    if not isinstance(scope, list) or not scope:
        errors.append(f"{where}: 'scope' must be a non-empty list of patterns.")
    elif not all(isinstance(pattern, str) and pattern for pattern in scope):
        errors.append(f"{where}: every entry in 'scope' must be a non-empty piece of text.")

    reason = declaration.get("reason", "")
    if not isinstance(reason, str) or not reason.strip():
        # The reason is shown to a person deciding whether to install the skill, so
        # a blank one hides exactly the information they need.
        errors.append(f"{where}: 'reason' must explain why the skill needs this.")
    elif len(reason) > 200:
        errors.append(f"{where}: 'reason' must be 200 characters or fewer.")


def _validate_parameters_schema(parameters: Any, errors: list[str]) -> None:
    """
    Check the description of the values the AI model must supply.

    In: the raw parameters description and the errors list. Out: nothing.

    The outermost type must be "object" (decision S-6). The AI model's tool format
    requires it, so catching it here turns a confusing failure at conversation time
    into a clear message in the skill store.
    """
    if not isinstance(parameters, dict):
        errors.append("invocation.parameters: must be a JSON Schema object.")
        return

    if parameters.get("type") != "object":
        errors.append(
            "invocation.parameters: the outermost 'type' must be \"object\", because "
            "that is what the AI model's tool format requires."
        )

    try:
        # Ask the schema library whether this is a valid schema at all. A broken
        # schema would otherwise fail much later, in the middle of a conversation.
        jsonschema.Draft202012Validator.check_schema(parameters)
    except jsonschema.exceptions.SchemaError as error:
        errors.append(f"invocation.parameters: not a valid JSON Schema ({error.message}).")


def parse_manifest(
    path: Path,
    vocabulary: Vocabulary,
    categories: set[str],
    trusted_keys: dict[str, str] | None = None,
) -> tuple[Manifest | None, list[str]]:
    """
    Read and check one skill's description file.

    In:
      path         - the manifest.json file;
      vocabulary   - the shared capability list;
      categories   - the category names the baselines file knows about;
      trusted_keys - the map of key id -> public key the deployment trusts
                     (REQ-09). Optional; when supplied, a signature claimed by one
                     of those trusted keys is verified.
    Out: a pair - the parsed Manifest (or None if it failed), and a list of every
    problem found.

    This function NEVER raises. It collects every problem it can find and returns
    them all together, so a skill author sees the whole list at once instead of
    fixing one typo at a time.
    """
    errors: list[str] = []
    path = Path(path)
    trusted_keys = trusted_keys or {}

    if not path.exists():
        return None, [f"No manifest.json found at {path}."]

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return None, [f"manifest.json is not valid JSON: {error}."]
    except OSError as error:
        return None, [f"manifest.json could not be read: {error}."]

    if not isinstance(raw, dict):
        return None, ["manifest.json must contain a JSON object at the top level."]

    # --- the simple required fields ---
    for field in ["id", "name", "version", "author", "category", "description", "entrypoint", "digest"]:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"'{field}' is required and must be non-empty text.")

    # Every manifest must bind a canonical sha256 digest of its own content. We check
    # the format here so an obvious typo is caught in the store; whether the digest
    # actually MATCHES the on-disk resources is verified at install and run (REQ-02).
    digest = raw.get("digest")
    if isinstance(digest, str) and digest.strip() and not SHA256_HEX.match(digest):
        errors.append(
            f"'digest' must be a sha256 hex digest (64 lower-case hex characters). "
            f"Got {digest!r}."
        )

    digest_alg = raw.get("digest_alg", "sha256")
    if digest_alg != "sha256":
        errors.append(
            f"'digest_alg' must be \"sha256\"; this lab only recognises sha256 "
            f"canonical digests. Got {digest_alg!r}."
        )

    # --- optional provenance: a signature over the digest (REQ-09) ---
    signature = raw.get("signature")
    sign_public_key_id = raw.get("sign_public_key_id")

    if signature is not None and (
        not isinstance(signature, str) or not SIGNATURE_HEX.match(signature)
    ):
        errors.append(
            f"'signature' must be a 64-byte Ed25519 signature as 128 hex "
            f"characters. Got {signature!r}."
        )

    if sign_public_key_id is not None and (
        not isinstance(sign_public_key_id, str) or not sign_public_key_id.strip()
    ):
        errors.append("'sign_public_key_id' must be non-empty text.")

    # A signature is only ever checked when its claimed key is one the deployment
    # actually trusts (a key it has in trusted_keys.json). An unsigned skill - or a
    # skill signed by a key nobody trusts - gets no benefit from the claim and is not
    # marked invalid for it. But a signature attributed to a TRUSTED key is required
    # to hold up, or the skill is refused.
    public_key = None
    if isinstance(sign_public_key_id, str) and sign_public_key_id in trusted_keys:
        public_key = trusted_keys[sign_public_key_id]

    if public_key is not None:
        if signature is None:
            errors.append(
                f"Skill claims to be signed with trusted key "
                f"{sign_public_key_id!r} but carries no 'signature'."
            )
        elif isinstance(signature, str) and SIGNATURE_HEX.match(signature):
            if isinstance(digest, str) and SHA256_HEX.match(digest):
                if not signing.verify_signature(public_key, signature, digest):
                    errors.append(
                        f"'signature' does not verify against trusted key "
                        f"{sign_public_key_id!r} for digest {digest[:16]}...; "
                        f"the skill may have been altered or signed by a key that "
                        f"is not the one it claims."
                    )

    skill_id = raw.get("id")
    if isinstance(skill_id, str) and not SKILL_ID_PATTERN.match(skill_id):
        errors.append(
            f"'id' must be 3-40 characters of lowercase letters, digits and "
            f"underscores, starting with a letter. Got {skill_id!r}."
        )

    entrypoint = raw.get("entrypoint")
    if isinstance(entrypoint, str) and not ENTRYPOINT_PATTERN.match(entrypoint):
        errors.append(
            f"'entrypoint' must look like \"skill.py:run\". Got {entrypoint!r}."
        )
    elif isinstance(entrypoint, str):
        # The file and the function it names must actually exist, or the skill would
        # only fail at the moment someone tried to use it.
        filename, _, attribute = entrypoint.partition(":")
        if not (path.parent / filename).exists():
            errors.append(f"'entrypoint' points at {filename}, which does not exist.")
        if not attribute:
            errors.append("'entrypoint' does not name a function to call.")

    category = raw.get("category")
    if isinstance(category, str) and category not in categories:
        errors.append(
            f"'category' is {category!r}, which has no entry in the baselines file. "
            f"Known categories: {', '.join(sorted(categories))}."
        )

    # --- how the AI model is told about this skill ---
    invocation = raw.get("invocation")
    if not isinstance(invocation, dict):
        errors.append("'invocation' is required and must be an object.")
    else:
        when_to_use = invocation.get("when_to_use")
        if not isinstance(when_to_use, str) or not when_to_use.strip():
            errors.append("'invocation.when_to_use' is required and must be non-empty text.")
        _validate_parameters_schema(invocation.get("parameters"), errors)

    # --- declared permissions ---
    capabilities = raw.get("capabilities", [])
    if not isinstance(capabilities, list):
        errors.append("'capabilities' must be a list (it may be empty).")
    else:
        for index, declaration in enumerate(capabilities):
            if not isinstance(declaration, dict):
                errors.append(f"capabilities[{index}]: must be an object.")
                continue
            _validate_capability(index, declaration, vocabulary, errors)

    if errors:
        return None, errors

    # Everything checked out; build the tidy object the rest of the app uses.
    try:
        return Manifest(**raw), []
    except Exception as error:
        return None, [f"manifest.json did not match the expected shape: {error}."]
