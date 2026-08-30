"""
The skill itself: found, accepted, honest on paper, pinned - and still compromised.

Three things are proved here, and they matter for different reasons.

FIRST, that the skill is completely clean by every measure the app can apply to it BEFORE
it runs. Its description is true, its permissions are exactly what its category allows, it
goes around nothing, and it even writes down the fingerprint of the component it expects.
This is not incidental - it IS the weakness. If a reviewer could catch this skill by
reading it, the point of AST02 would be lost. The tests below are therefore written as
"confirm there is nothing to find", which is an unusual shape for a weakness's tests and is
deliberate.

SECOND, that the promise it makes is real and stays real. The fingerprint in its
description is recomputed here from the build that ships beside it, so the two can never
drift apart quietly. And the address it says it fetches from is compared, character for
character, with the address it actually goes to - because a check that compares a promise
to a delivery is worthless if the promise is about a different place.

THIRD, that it really does act only through the official channel, so everything it does is
visible in the ordinary record.

Specification references: AST02 spec sections 6.3, 6.4 and 7.4; decisions S-3, S-5, S-12,
S-13, S-14; acceptance tests A-13 and A-18; build plan step 7.2.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.findings.baselines import load_baselines
from app.findings.engine import FindingsEngine
from app.monitor.observations import digest_of
from app.skills import registry as registry_module
from app.skills.manifest import load_vocabulary
from tests.source_tools import called_function_names, executable_source, imported_modules

SKILL_DIR = Path(__file__).resolve().parents[1] / "skill" / "time_budget"
SKILL_FILE = SKILL_DIR / "skill.py"
MANIFEST_FILE = SKILL_DIR / "manifest.json"
REVIEWED_BUILD = (
    Path(__file__).resolve().parents[1] / "registry" / "sizing-heuristics-2.3.1.reviewed.json"
)


def test_the_app_finds_and_accepts_the_skill(tmp_settings):
    """
    Adding the folder is the whole of the wiring, and the description passes every check.

    A malformed component block would make the skill invalid and it could never be
    installed - a description that cannot be read is a typo, not an attack. This one is
    spotless, which is the point.
    """
    registry_module.reset_registry()
    registry = registry_module.get_registry()
    registry.discover_default()

    record = registry.get("time_budget")
    assert record.valid is True
    assert record.errors == []
    assert record.manifest.category == "integration"


def test_the_manifest_declares_exactly_what_the_code_uses(tmp_settings):
    """
    Nothing undeclared, nothing declared and unused - so the truthfulness check has nothing
    to say and neither does the "power it never uses" one.
    """
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    declared = {capability["id"] for capability in manifest["capabilities"]}

    assert declared == {"task.read", "net.outbound"}

    source = SKILL_FILE.read_text(encoding="utf-8")
    # It uses both, so neither is dormant.
    assert "ctx.tasks.list" in source
    assert "ctx.net.get" in source
    # And it uses nothing else that would need declaring.
    assert "ctx.net.post" not in source
    assert "ctx.files" not in source
    assert "ctx.env" not in source
    assert "ctx.tasks.add" not in source
    assert "ctx.tasks.update" not in source
    assert "ctx.tasks.delete" not in source


def test_the_grant_is_exactly_what_its_category_allows(tmp_settings):
    """
    The permissions are right-sized, so the proportionality check stays silent.

    Measured against the real policy file rather than a copy of it, so this cannot drift
    apart from what the app actually enforces. Note that this is the identical pair of
    permissions the theft demonstration declares - proportionality is a property of a
    permission relative to a job, not of the permission itself.
    """
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")
    integration = baselines["integration"]

    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))

    for capability in manifest["capabilities"]:
        assert capability["id"] in integration.allowed, (
            f"{capability['id']} is outside the integration baseline, which would make "
            f"this an over-privileged skill as well and spoil the demonstration"
        )

    network = next(c for c in manifest["capabilities"] if c["id"] == "net.outbound")
    assert network["scope"] == ["127.0.0.1"]


def test_installing_it_raises_nothing_at_all(tmp_settings):
    """
    Read the description as carefully as the app can, and there is still nothing wrong.

    This is the sentence the whole weakness rests on: **reviewing a skill tells you nothing
    about the code it pulls in.** The component is pinned, so there is not even the mild
    "you promised nothing" complaint to make. The dangerous part is not in the skill and
    does not exist until something is delivered.
    """
    vocabulary = load_vocabulary(tmp_settings.policy_dir / "capability_vocabulary.json")
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")

    registry_module.reset_registry()
    registry = registry_module.get_registry()
    registry.discover_default()
    manifest = registry.get("time_budget").manifest

    engine = FindingsEngine(vocabulary, baselines)

    assert engine.evaluate_install(manifest) == []


# --- A-18: the promise is real, and cannot drift ------------------------------------


def test_the_pinned_fingerprint_matches_the_reviewed_build(tmp_settings):
    """
    A-18 - the fingerprint in the description really is the fingerprint of the build
    shipped beside it.

    Recomputed here rather than copied, using the app's own recipe, so the two can never
    drift apart in silence. If someone edits the reviewed build and forgets to regenerate
    the pin, this fails immediately - instead of the weakness quietly becoming undetectable
    because the pin no longer matches anything at all.

    Note the recipe: this is NOT a plain checksum of the file. It is the fingerprint the
    app itself records when the component is delivered. Defining the pin that way is what
    makes the later comparison exact.
    """
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    declared = manifest["dependencies"][0]["integrity"]

    reviewed_text = REVIEWED_BUILD.read_bytes().decode("utf-8")
    expected = f"sha256:{digest_of(reviewed_text)}"

    assert declared == expected, (
        "The pinned fingerprint no longer matches the reviewed build. Regenerate it - see "
        "vulnerabilities/ast02-supply-chain/registry/README.md - rather than deleting this "
        "test."
    )


def test_the_declared_source_is_the_address_the_skill_actually_uses(tmp_settings):
    """
    A-18 - the place the description names and the place the code goes are the same place.

    This coupling is load-bearing and easy to break by tidying either side. The check that
    compares a promise against a delivery finds the delivery by matching the address, so if
    the two drifted apart by so much as a trailing slash the promise would be about
    something that never arrived and the weakness would become invisible - with every test
    name still intact.
    """
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    declared_source = manifest["dependencies"][0]["source"]

    source = executable_source(SKILL_FILE).replace("'", '"')
    assert f'PACK_URL = "{declared_source}"' in source, (
        "the address the skill fetches from is not byte-for-byte the one it declares"
    )


def test_the_component_is_declared_completely(tmp_settings):
    """
    The description says which component, which version, from where, from whom, and why.

    All five are what make the finding readable by a person later: "you were promised this
    exact build of this exact thing, and got something else".
    """
    registry_module.reset_registry()
    registry = registry_module.get_registry()
    registry.discover_default()

    dependencies = registry.get("time_budget").manifest.dependencies
    assert len(dependencies) == 1

    component = dependencies[0]
    assert component.name == "sizing-heuristics"
    assert component.version == "2.3.1"
    assert component.publisher == "Loft Analytics"
    assert component.source.startswith("http://127.0.0.1:8000/")
    assert component.integrity is not None
    assert component.reason.strip() != ""


# --- A-13: through the broker, not around it ----------------------------------------


def test_it_acts_only_through_the_official_channel(tmp_settings):
    """
    A-13 - the skill goes around nothing, so everything it does is on the record.

    It imports the app's own result types, a JSON reader and a clock, and nothing that
    could reach a file, a socket or another program. The JSON reader only turns text into
    data; the clock is used to work out how old a task is. Every sibling weakness bans the
    same reaching modules.

    If any of them appeared, the skill would be going around the app - which is a
    different, separately reported problem, and would muddy this demonstration.
    """
    modules = imported_modules(SKILL_FILE)
    reaching = {"os", "sys", "socket", "httpx", "subprocess", "pathlib", "urllib", "shutil", "io"}

    assert modules & reaching == set(), f"the skill reaches around the app via {modules & reaching}"
    assert modules <= {"app", "json", "datetime"}, (
        f"unexpected imports: {modules - {'app', 'json', 'datetime'}}"
    )

    called = called_function_names(SKILL_FILE)
    for forbidden in ("open", "eval", "exec", "compile", "__import__"):
        assert forbidden not in called, f"the skill calls {forbidden}()"


def test_the_fetched_component_is_read_as_data_and_never_run(tmp_settings):
    """
    A "supply chain compromise" that actually ran downloaded code would be outside this
    app's safety promise.

    What arrives is a table of bands and numbers, and it is walked, not executed. This
    keeps the demonstration real - a substituted component genuinely changes what the user
    is told - while nothing fetched is ever given the chance to run.
    """
    source = executable_source(SKILL_FILE)

    for forbidden in ("exec(", "eval(", "compile(", "__import__", "importlib"):
        assert forbidden not in source, f"the skill runs fetched content via {forbidden}"


def test_the_skill_does_not_check_what_it_was_given(tmp_settings):
    """
    The absence of any verification is the weakness, and it is pinned so nobody "fixes" it.

    A future tidy-up that compared the delivered component against the pinned fingerprint
    would quietly delete the vulnerability while leaving every test name intact. This makes
    that change fail loudly instead.

    The CODE only - the explanations above it discuss fingerprints at length while
    explaining that the skill never checks one, and a plain text search would trip over its
    own documentation.
    """
    source = executable_source(SKILL_FILE)

    assert "integrity" not in source, (
        "the skill now looks at the pinned fingerprint. Verifying what arrived is "
        "remediation, which this app deliberately does not do - it would delete the "
        "weakness this skill exists to demonstrate."
    )
    assert "digest_of" not in source
    assert "sha256" not in source


def test_no_parameter_carries_the_attack(tmp_settings):
    """
    The model cannot influence which component is fetched.

    The only thing it may pass is which tasks to look at. The address is fixed in the code
    and the pin is fixed in the description, so the finding does not depend on what the
    model happened to say - which is what makes the demonstration repeatable rather than
    lucky.
    """
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    properties = manifest["invocation"]["parameters"]["properties"]

    assert set(properties) == {"scope"}
    assert properties["scope"]["enum"] == ["open", "all"]
