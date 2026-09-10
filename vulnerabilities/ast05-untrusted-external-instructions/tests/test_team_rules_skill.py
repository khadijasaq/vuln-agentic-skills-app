"""
The skill itself: found, accepted, honest on paper, and acting only through the app.

Two things are proved here, and they matter for opposite reasons.

FIRST, that the skill is completely clean by every measure the app can apply to it
BEFORE it runs. Its manifest is true, its permissions are exactly what its category
allows, it goes around nothing. This is not incidental - it IS the weakness. If a
reviewer could catch this skill by reading it, the point of AST05 would be lost. The
tests below are therefore written as "confirm there is nothing to find", which is an
unusual shape for a weakness's tests and is deliberate.

SECOND, that it really does act only through the official channel. Everything it does is
therefore visible in the ordinary record, which is what makes the evidence trustworthy.

Specification references: feature spec sections 5.2, 5.3 and 5.4; decisions S-12, S-13,
S-15; acceptance test A-11.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.findings.baselines import load_baselines
from app.findings.engine import FindingsEngine
from app.skills import registry as registry_module
from app.skills.manifest import load_vocabulary
from tests.source_tools import called_function_names, executable_source, imported_modules

SKILL_DIR = Path(__file__).resolve().parents[1] / "skill" / "team_rules"
SKILL_FILE = SKILL_DIR / "skill.py"
MANIFEST_FILE = SKILL_DIR / "manifest.json"


def test_the_app_finds_and_accepts_the_skill(tmp_settings):
    """
    Adding the folder is the whole of the wiring, and the manifest passes every check.

    An over-declared or malformed manifest would make the skill invalid and it could never
    be installed. This one is spotless - which is the point.
    """
    registry_module.reset_registry()
    registry = registry_module.get_registry()
    registry.discover_default()

    record = registry.get("team_rules")
    assert record.valid is True
    assert record.errors == []
    assert record.manifest.category == "integration"


def test_the_manifest_declares_exactly_what_the_code_uses(tmp_settings):
    """
    Nothing undeclared, nothing declared and unused - so the truthfulness check has
    nothing to say and neither does the "power it never uses" one.

    This is checked against the SOURCE rather than a run, so it stays true regardless of
    which document happens to be served.
    """
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    declared = {capability["id"] for capability in manifest["capabilities"]}

    assert declared == {"task.read", "net.outbound"}

    source = SKILL_FILE.read_text(encoding="utf-8")
    # It uses both, so neither is dormant.
    assert "ctx.tasks.list" in source
    assert "ctx.net.get" in source
    assert "ctx.net.post" in source
    # And it uses nothing else that would need declaring.
    assert "ctx.files" not in source
    assert "ctx.env" not in source
    assert "ctx.tasks.add" not in source
    assert "ctx.tasks.update" not in source
    assert "ctx.tasks.delete" not in source


def test_the_grant_is_exactly_what_its_category_allows(tmp_settings):
    """
    The permissions are right-sized, so the proportionality check stays silent.

    Measured against the real policy file rather than a copy of it, so this cannot drift
    apart from what the app actually enforces.
    """
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")
    integration = baselines["integration"]

    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))

    for capability in manifest["capabilities"]:
        assert capability["id"] in integration.allowed, (
            f"{capability['id']} is outside the integration baseline, which would make "
            f"this an over-privileged skill as well and spoil the demonstration"
        )

    # The network scope is exactly the yardstick's limit - not narrower, not wider.
    network = next(c for c in manifest["capabilities"] if c["id"] == "net.outbound")
    assert network["scope"] == ["127.0.0.1"]


def test_the_manifest_alone_raises_nothing(tmp_settings):
    """
    Read the manifest as carefully as the app can, and there is still nothing wrong.

    This is the sentence the whole weakness rests on: **reviewing a skill tells you
    nothing here.** The dangerous part is not in the skill and does not exist until it
    runs.
    """
    vocabulary = load_vocabulary(tmp_settings.policy_dir / "capability_vocabulary.json")
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")

    registry_module.reset_registry()
    registry = registry_module.get_registry()
    registry.discover_default()
    manifest = registry.get("team_rules").manifest

    engine = FindingsEngine(vocabulary, baselines)

    assert engine.evaluate_install(manifest) == []


def test_it_acts_only_through_the_official_channel(tmp_settings):
    """
    A-11 - the skill goes around nothing, so everything it does is on the record.

    It imports the app's own result types and the JSON reader, and nothing that could
    reach a file, a socket or another program. The JSON reader is worth a word: it only
    turns text into data and cannot reach anything, and the skill needs it to read the
    document it fetched. Every sibling weakness bans the same reaching modules.

    If any of them appeared, the skill would be going around the app - which is a
    different, separately reported problem, and would muddy this demonstration.
    """
    modules = imported_modules(SKILL_FILE)
    reaching = {"os", "sys", "socket", "httpx", "subprocess", "pathlib", "urllib", "shutil", "io"}

    assert modules & reaching == set(), f"the skill reaches around the app via {modules & reaching}"
    assert modules <= {"app", "json"}, f"unexpected imports: {modules - {'app', 'json'}}"

    called = called_function_names(SKILL_FILE)
    for forbidden in ("open", "eval", "exec", "compile", "__import__"):
        assert forbidden not in called, f"the skill calls {forbidden}()"


def test_the_skill_does_not_defend_itself_against_the_document(tmp_settings):
    """
    The absence of any checking is the weakness, and it is pinned so nobody "fixes" it.

    A future tidy-up that added an allowlist for the destination, or escaped the planted
    line, would quietly delete the vulnerability while leaving every test name intact.
    This makes that change fail loudly instead.
    """
    # The CODE only - the explanations above it say the word "allowlist" while explaining
    # that there is not one, and a plain text search would trip over its own documentation.
    # That helper also normalises quotes, so compare without caring which kind was used.
    source = executable_source(SKILL_FILE).replace("'", '"')
    flat = " ".join(source.split())

    # The destination is taken straight from the document, and goes to the sender unchecked.
    assert 'document.get("report_to")' in source
    assert "ctx.net.post( report_to" in flat or "ctx.net.post(report_to" in flat

    # The planted line is added to what the skill returns, unaltered.
    assert 'document.get("notice")' in source
    assert "{message} {notice}" in source

    # And there is nothing between the document and the action that could soften either.
    for defence in ("ALLOWED_REPORT", "allowlist", "ALLOWED_HOSTS", "sanitize", "sanitise", "escape("):
        assert defence not in source, (
            f"the skill has grown a defence ({defence}). That is remediation, which this "
            f"app deliberately does not do - it would delete the vulnerability."
        )
