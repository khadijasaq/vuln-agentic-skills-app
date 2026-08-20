"""
Checks for reading and validating a skill's description file (app/skills/manifest.py).

Two properties matter most here:

  1. Checking a manifest NEVER throws an error. It returns everything that is wrong,
     all at once, so a skill author can fix the whole list in one pass.
  2. A broken manifest makes a skill "invalid", NOT a security finding. A skill that
     cannot run cannot misbehave, and a typo is not an attack.

Covers: feature spec sections 3.5 and 5.3, TDD section 2.2, decision S-6.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.skills.manifest import load_category_names, load_vocabulary, parse_manifest


# A complete, correct manifest used as the starting point for these tests. Each test
# changes one thing about it, which keeps it obvious what is being checked.
GOOD_MANIFEST = {
    "schema_version": 1,
    "id": "example_skill",
    "name": "Example Skill",
    "version": "1.0.0",
    "author": "TaskBot Labs",
    "category": "reporting",
    "description": "An example used only by the automated checks.",
    "invocation": {
        "when_to_use": "When a test needs a manifest that passes every check.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "capabilities": [
        {"id": "task.read", "scope": ["*"], "reason": "Reads tasks for the example."}
    ],
    "entrypoint": "skill.py:run",
}


@pytest.fixture
def policy(tmp_settings):
    """The real capability list and category names, as the running app uses them."""
    vocabulary = load_vocabulary(tmp_settings.policy_dir / "capability_vocabulary.json")
    categories = load_category_names(
        tmp_settings.policy_dir / "capability_baselines.json"
    )
    return vocabulary, categories


def write_skill(folder: Path, manifest: dict, with_code: bool = True) -> Path:
    """
    Write a skill folder for a test.

    In: the folder to create, the manifest to write, and whether to also create the
    code file the manifest points at.
    Out: the path of the manifest file.
    """
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if with_code:
        (folder / "skill.py").write_text("def run(ctx, params):\n    pass\n", encoding="utf-8")
    return manifest_path


# --- The happy path --------------------------------------------------------------


def test_a_correct_manifest_parses_with_no_problems(tmp_path, policy):
    """The baseline: a well-formed manifest is accepted."""
    vocabulary, categories = policy
    path = write_skill(tmp_path / "example_skill", GOOD_MANIFEST)

    manifest, errors = parse_manifest(path, vocabulary, categories)

    assert errors == []
    assert manifest is not None
    assert manifest.id == "example_skill"
    assert manifest.capabilities[0].id == "task.read"


# --- Things that make a manifest invalid -----------------------------------------


def test_a_missing_manifest_is_reported_not_crashed(tmp_path, policy):
    """A folder with no manifest reports the problem instead of throwing."""
    vocabulary, categories = policy

    manifest, errors = parse_manifest(tmp_path / "nothing" / "manifest.json", vocabulary, categories)

    assert manifest is None
    assert len(errors) == 1


def test_unreadable_json_is_reported_not_crashed(tmp_path, policy):
    """Broken JSON is a clear message, not an exception travelling up the app."""
    vocabulary, categories = policy
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "manifest.json").write_text("{ this is not json", encoding="utf-8")

    manifest, errors = parse_manifest(folder / "manifest.json", vocabulary, categories)

    assert manifest is None
    assert any("not valid JSON" in error for error in errors)


def test_a_bad_identifier_is_rejected(tmp_path, policy):
    """
    Identifiers double as the name the AI model uses to ask for a skill, so they
    must be simple and predictable.
    """
    vocabulary, categories = policy
    for bad_id in ["Has Capitals", "with-dashes", "ab", "1starts_with_digit", ""]:
        broken = {**GOOD_MANIFEST, "id": bad_id}
        path = write_skill(tmp_path / f"bad_{abs(hash(bad_id))}", broken)

        manifest, errors = parse_manifest(path, vocabulary, categories)

        assert manifest is None, f"{bad_id!r} should have been rejected"
        assert errors


def test_an_unknown_category_is_rejected(tmp_path, policy):
    """
    Every category must exist in the yardstick file, or there would be nothing to
    measure the skill's power against.
    """
    vocabulary, categories = policy
    broken = {**GOOD_MANIFEST, "category": "invented_category"}
    path = write_skill(tmp_path / "bad_category", broken)

    manifest, errors = parse_manifest(path, vocabulary, categories)

    assert manifest is None
    assert any("category" in error for error in errors)


def test_an_unknown_capability_is_rejected(tmp_path, policy):
    """
    A skill may only declare permissions from the shared vocabulary. An invented one
    could not be compared against anything the watchers record.
    """
    vocabulary, categories = policy
    broken = {
        **GOOD_MANIFEST,
        "capabilities": [{"id": "database.drop", "scope": ["*"], "reason": "why not"}],
    }
    path = write_skill(tmp_path / "bad_capability", broken)

    manifest, errors = parse_manifest(path, vocabulary, categories)

    assert manifest is None
    assert any("database.drop" in error for error in errors)


def test_an_empty_scope_is_rejected(tmp_path, policy):
    """
    Declaring a permission with no limits at all is almost certainly a mistake, and
    an empty list is too easily confused with "unlimited".
    """
    vocabulary, categories = policy
    broken = {
        **GOOD_MANIFEST,
        "capabilities": [{"id": "task.read", "scope": [], "reason": "reads tasks"}],
    }
    path = write_skill(tmp_path / "empty_scope", broken)

    manifest, errors = parse_manifest(path, vocabulary, categories)

    assert manifest is None
    assert any("scope" in error for error in errors)


def test_a_missing_reason_is_rejected(tmp_path, policy):
    """
    The reason is what a person reads when deciding whether to trust a skill, so a
    blank one hides exactly the information they need.
    """
    vocabulary, categories = policy
    broken = {
        **GOOD_MANIFEST,
        "capabilities": [{"id": "task.read", "scope": ["*"], "reason": "  "}],
    }
    path = write_skill(tmp_path / "no_reason", broken)

    manifest, errors = parse_manifest(path, vocabulary, categories)

    assert manifest is None
    assert any("reason" in error for error in errors)


def test_parameters_must_be_an_object_at_the_top(tmp_path, policy):
    """
    DECISION S-6.

    The AI model's tool format requires the outermost type to be "object". Catching
    it here turns a confusing mid-conversation failure into a clear store message.
    """
    vocabulary, categories = policy
    broken = {
        **GOOD_MANIFEST,
        "invocation": {
            "when_to_use": "whenever",
            "parameters": {"type": "string"},
        },
    }
    path = write_skill(tmp_path / "bad_params", broken)

    manifest, errors = parse_manifest(path, vocabulary, categories)

    assert manifest is None
    assert any("object" in error for error in errors)


def test_an_invalid_parameter_schema_is_rejected(tmp_path, policy):
    """A parameter description that is not a valid schema at all is caught early."""
    vocabulary, categories = policy
    broken = {
        **GOOD_MANIFEST,
        "invocation": {
            "when_to_use": "whenever",
            "parameters": {"type": "object", "properties": {"x": {"type": 12345}}},
        },
    }
    path = write_skill(tmp_path / "bad_schema", broken)

    manifest, errors = parse_manifest(path, vocabulary, categories)

    assert manifest is None
    assert errors


def test_a_missing_code_file_is_rejected(tmp_path, policy):
    """
    A manifest pointing at code that does not exist would only fail at the moment
    someone tried to use the skill. Better to catch it in the store.
    """
    vocabulary, categories = policy
    path = write_skill(tmp_path / "no_code", GOOD_MANIFEST, with_code=False)

    manifest, errors = parse_manifest(path, vocabulary, categories)

    assert manifest is None
    assert any("does not exist" in error for error in errors)


def test_a_bad_entrypoint_format_is_rejected(tmp_path, policy):
    """The entrypoint must name a file and a function, like "skill.py:run"."""
    vocabulary, categories = policy
    broken = {**GOOD_MANIFEST, "entrypoint": "skill.py"}
    path = write_skill(tmp_path / "bad_entry", broken)

    manifest, errors = parse_manifest(path, vocabulary, categories)

    assert manifest is None
    assert any("entrypoint" in error for error in errors)


# --- The behaviour that makes fixing manifests bearable --------------------------


def test_every_problem_is_reported_at_once(tmp_path, policy):
    """
    A manifest with several faults reports ALL of them together, rather than making
    the author fix one, re-run, and discover the next.
    """
    vocabulary, categories = policy
    very_broken = {
        **GOOD_MANIFEST,
        "id": "BAD ID",
        "category": "invented",
        "capabilities": [{"id": "not.a.capability", "scope": [], "reason": ""}],
    }
    path = write_skill(tmp_path / "many_problems", very_broken)

    manifest, errors = parse_manifest(path, vocabulary, categories)

    assert manifest is None
    assert len(errors) >= 3


def test_checking_a_manifest_never_raises(tmp_path, policy):
    """
    Whatever nonsense is in the file, this must return a result rather than throw.
    The skill store has to be able to display every skill, including the broken ones.
    """
    vocabulary, categories = policy
    nasty_inputs = ["", "null", "[]", '"just a string"', "{}", "12345"]

    for index, content in enumerate(nasty_inputs):
        folder = tmp_path / f"nasty_{index}"
        folder.mkdir()
        (folder / "manifest.json").write_text(content, encoding="utf-8")

        # Must not raise.
        manifest, errors = parse_manifest(folder / "manifest.json", vocabulary, categories)
        assert manifest is None
        assert errors
