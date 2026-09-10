"""
Is the supply-chain check a real check, or a rubber stamp?

THIS IS THE FILE THAT ANSWERS THE OBJECTION. AST02 is the second weakness to change the
shared platform, and the fair question about any such change is: *if you had to add a check
to make your vulnerability visible, did you find a vulnerability or did you build one?*

The honest answer is not an argument, it is a measurement, and it has three parts:

  1. The check STAYS SILENT when the agreed component is delivered. Same skill, same
     description, same fetch - and nothing to report. A check that cannot be quiet is not a
     check.
  2. The check FIRES when a different component is delivered, even a completely harmless
     one - because it is about identity, not behaviour. That is what separates it from
     every other question this app asks.
  3. The check has NOTHING to say about a skill that promised nothing, fetched nothing, or
     was handed nothing. Silence in those cases is structural, not lucky.

Everything here is built by hand and fed straight to the engine - fabricated descriptions
and fabricated records of what a skill supposedly did. Nothing runs, which is what lets a
single test state a precise claim about one thing.

Specification references: AST02 spec sections 7.2, 7.4, 9.8 and 10.3; acceptance tests
A-6, A-7, A-11 and A-14; build plan step 7.3.
"""

from __future__ import annotations

import pytest

from app.findings.baselines import load_baselines
from app.findings.engine import FindingsEngine
from app.monitor.observations import ObservationLog, digest_of
from app.skills.manifest import load_vocabulary
from tests.test_engine import make_manifest

PACK_URL = "http://127.0.0.1:8000/mock/registry/sizing-heuristics/2.3.1"

# A component that behaves itself: the build the skill's author reviewed.
REVIEWED_BODY = '{"pack": "sizing-heuristics", "version": "2.3.1", "rules": ["reviewed"]}'

# The same component, at the same version, with different contents.
SUBSTITUTED_BODY = '{"pack": "sizing-heuristics", "version": "2.3.1", "rules": ["substituted"]}'

REVIEWED_PIN = f"sha256:{digest_of(REVIEWED_BODY)}"


@pytest.fixture
def engine(tmp_settings) -> FindingsEngine:
    """An engine loaded with the app's real capability list and yardstick policy."""
    vocabulary = load_vocabulary(tmp_settings.policy_dir / "capability_vocabulary.json")
    baselines = load_baselines(tmp_settings.policy_dir / "capability_baselines.json")
    return FindingsEngine(vocabulary, baselines)


def depending_skill(pin: str | None = REVIEWED_PIN, source: str = PACK_URL):
    """
    A description that declares one component from elsewhere.

    In: the fingerprint it pins (or nothing, for a skill that pins none) and where it says
    the component comes from. Out: a Manifest.
    """
    component = {
        "name": "sizing-heuristics",
        "version": "2.3.1",
        "publisher": "Loft Analytics",
        "source": source,
        "reason": "The sizing bands this skill applies.",
    }
    if pin is not None:
        component["integrity"] = pin

    return make_manifest(
        skill_id="depending_skill",
        category="integration",
        capabilities=[
            {"id": "task.read", "scope": ["*"], "reason": "reads tasks"},
            {"id": "net.outbound", "scope": ["127.0.0.1"], "reason": "fetches the component"},
        ],
        dependencies=[component],
    )


def delivery(body: str, *, url: str = PACK_URL, status: int = 200, read_first: bool = True):
    """
    A record of a skill reading its tasks and then being handed a component.

    In: what came back, from where, and with what status.
    Out: the observations, in the order they happened.

    The task read comes first and the fetch last, which is the order the real skill uses -
    and which matters, because it leaves nothing after the fetch for the fetched content to
    have steered.
    """
    log = ObservationLog("inv_test")

    if read_first:
        log.record(
            capability="task.read",
            resource="*",
            detail={"scope": "open", "count": 3, "sha256": digest_of(["a", "b", "c"])},
        )

    detail = {"method": "GET", "status": status}
    if status == 200 or status == 404:
        # A reply arrived either way - the app fingerprints whatever came back, including
        # an error page. Whether an error page counts as a DELIVERY is exactly the question
        # this axis has to get right.
        detail["response_bytes"] = len(body.encode("utf-8"))
        detail["response_sha256"] = digest_of(body)
        detail["response_item_digests"] = [digest_of(body)]
        detail["response_strings"] = [body]

    log.record(capability="net.outbound", resource=url, detail=detail)
    return log.entries()


def types_of(findings) -> list[str]:
    """Just the kinds of problem found, for readable assertions."""
    return sorted(finding.type for finding in findings)


# --- A-6: the agreed component raises nothing ---------------------------------------


def test_the_agreed_component_raises_nothing(engine):
    """
    A-6 - THE TEST THAT ANSWERS THE WHOLE OBJECTION.

    The skill declared a component and pinned a fingerprint. That exact component was
    delivered. There is nothing to report, and the check says nothing.

    Same skill, same description, same fetch, same everything - the ONLY difference from
    the case that fires is which bytes arrived. If this test ever fails, the check has
    stopped being a check and become a thing that fires whenever a skill fetches anything,
    which is exactly the accusation the platform change had to answer.
    """
    findings = engine.evaluate_invocation(
        depending_skill(), delivery(REVIEWED_BODY), invocation_id="inv_1"
    )

    assert findings == []


def test_the_agreed_component_raises_nothing_even_when_its_contents_are_alarming(engine):
    """
    A-6, the harder half - the delivered component says something startling, and this check
    still has nothing to say.

    This axis reads the FINGERPRINT of what arrived and never the contents. A component
    full of instructions, addresses or anything else is not its business: if it is the
    component that was agreed, then as far as "is this what you asked for?" goes, the answer
    is yes.

    That is not a gap. It is the line between this question and the one about being told
    what to do at run time, and keeping the two apart is what stops five checks collapsing
    into one vague one.
    """
    alarming = '{"pack": "sizing-heuristics", "report_to": "http://127.0.0.1:8000/mock/collector"}'
    pinned_to_the_alarming_one = f"sha256:{digest_of(alarming)}"

    findings = engine.check_integrity(
        depending_skill(pin=pinned_to_the_alarming_one),
        delivery(alarming),
        invocation_id="inv_1",
    )

    assert findings == []


# --- A-6 confirmed from the other side: it CAN fire ---------------------------------


def test_a_substituted_component_is_reported(engine):
    """
    The positive control. Change one thing - which bytes arrived - and the check fires.

    Everything about the skill is identical to the silent case above. Only the delivery
    differs.
    """
    findings = engine.check_integrity(
        depending_skill(), delivery(SUBSTITUTED_BODY), invocation_id="inv_1"
    )

    assert types_of(findings) == ["COMPROMISED_DEPENDENCY"]

    finding = findings[0]
    assert finding.ast_id == "AST02"
    assert finding.axis == "integrity"
    assert finding.severity == "high"
    assert finding.trigger == "invocation"

    # The evidence names the component, both fingerprints, and the moment it arrived.
    assert finding.dependency["name"] == "sizing-heuristics"
    assert finding.dependency["version"] == "2.3.1"
    assert finding.dependency["publisher"] == "Loft Analytics"
    assert finding.dependency["source"] == PACK_URL
    assert finding.dependency["declared_integrity"] == REVIEWED_PIN
    assert finding.dependency["delivered_integrity"] == f"sha256:{digest_of(SUBSTITUTED_BODY)}"
    assert finding.dependency["reason"] == "digest_mismatch"
    assert finding.dependency["acquired_seq"] == 2

    # And it fills only its own evidence slot, so a reader can tell which question it
    # answers without reading the wording.
    assert finding.observed is None
    assert finding.granted is None
    assert finding.correlation is None
    assert finding.provenance is None


# --- A-7: identity, not behaviour ----------------------------------------------------


def test_a_completely_harmless_substitution_still_fires(engine):
    """
    A-7 - THE TEST THAT SEPARATES THIS QUESTION FROM EVERY OTHER ONE.

    The delivered component is the reviewed one with a comment added. It does nothing
    wrong. It could not: it is the same rules, the same numbers, plus a line of prose.

    And it is still reported, because this check is not about what a component DOES. It is
    about whether what arrived is what was agreed. Every other question this app asks is
    defined over behaviour and could never fire here.

    That is what integrity pinning means in the real world, and reporting the mismatch
    rather than a judgement about it is the honest claim.
    """
    harmless = (
        '{"pack": "sizing-heuristics", "version": "2.3.1", "rules": ["reviewed"], '
        '"note": "rebuilt on a different machine"}'
    )

    findings = engine.evaluate_invocation(
        depending_skill(), delivery(harmless), invocation_id="inv_1"
    )

    assert types_of(findings) == ["COMPROMISED_DEPENDENCY"]
    assert findings[0].dependency["reason"] == "digest_mismatch"


# --- A-11: promising nothing is its own, milder problem ------------------------------


def test_a_component_with_no_pin_is_reported_at_install(engine):
    """
    A-11 - "you said which component, but not what it should look like."

    Nothing has gone wrong yet and nothing may ever. But nothing about what arrives can be
    checked, which is worth saying out loud - and can be said before the skill has ever run,
    because it is visible in the description alone.
    """
    findings = engine.evaluate_install(depending_skill(pin=None))

    assert types_of(findings) == ["UNPINNED_DEPENDENCY"]

    finding = findings[0]
    assert finding.ast_id == "AST02"
    assert finding.axis == "integrity"
    assert finding.severity == "low"
    assert finding.trigger == "install"
    assert finding.dependency["reason"] == "no_pin_declared"
    assert finding.dependency["declared_integrity"] is None
    assert finding.dependency["acquired_seq"] is None
    assert finding.observed is None


def test_an_unpinned_component_never_becomes_a_mismatch(engine):
    """
    A-11, the other half - with no promise there is nothing to compare, however odd the
    delivery.

    The skill still gets its "you promised nothing" note on the run, but never a mismatch:
    you cannot fail to match a fingerprint you never wrote down.
    """
    findings = engine.check_integrity(
        depending_skill(pin=None), delivery(SUBSTITUTED_BODY), invocation_id="inv_1"
    )

    assert types_of(findings) == ["UNPINNED_DEPENDENCY"]


def test_a_pinned_component_is_never_reported_as_unpinned(engine):
    """The two problems are alternatives, never both at once for the same component."""
    findings = engine.check_integrity(
        depending_skill(), delivery(SUBSTITUTED_BODY), invocation_id="inv_1"
    )

    assert "UNPINNED_DEPENDENCY" not in types_of(findings)


# --- A-14: nothing delivered means nothing to compare --------------------------------


def test_an_empty_registry_raises_nothing(engine):
    """
    A-14 - the component is simply not there, and that is not a compromise.

    This case is worth stating carefully, because it is the one that would quietly turn
    this check into a nuisance. When the registry has nothing to offer it answers with a
    short error, and the app fingerprints that error exactly as it fingerprints anything
    else that comes back. Comparing THAT fingerprint against the pin would report a
    substituted component every single time a lab was merely empty.

    So only a successful delivery is compared. An error page is not a build of anything.
    """
    missing = '{"error": "no_such_component", "detail": "nothing published here"}'

    findings = engine.check_integrity(
        depending_skill(), delivery(missing, status=404), invocation_id="inv_1"
    )

    assert findings == []


def test_a_refused_request_raises_nothing(engine):
    """
    A-14 - a request the app would not make delivered nothing, so there is nothing to
    compare.

    Worth contrasting with the check about being told what to do at run time, where a
    refused action still counts because the intent came from outside. Here the question is
    only "is what arrived what was agreed?", and nothing arrived. Reporting a compromise
    would be inventing evidence.
    """
    log = ObservationLog("inv_test")
    log.record(capability="task.read", resource="*", detail={"scope": "open"})
    refused = log.record(capability="net.outbound", resource=PACK_URL, detail={"method": "GET"})
    log.mark_refused(refused, "non_local_host")

    findings = engine.check_integrity(depending_skill(), log.entries(), invocation_id="inv_1")

    assert findings == []


def test_a_component_that_was_never_fetched_raises_nothing(engine):
    """
    A declared component that the skill never went and got has nothing to compare either.

    A stated limit, not an oversight: this check compares a promise to a delivery, and here
    there was no delivery.
    """
    log = ObservationLog("inv_test")
    log.record(capability="task.read", resource="*", detail={"scope": "open"})

    findings = engine.check_integrity(depending_skill(), log.entries(), invocation_id="inv_1")

    assert findings == []


def test_a_delivery_from_a_different_address_is_not_this_component(engine):
    """
    The promise is about a particular place, and a delivery from somewhere else is not it.

    Matching is on the address exactly as written. A near-match would be a guess, and this
    check exists to state facts rather than guesses. The cost is that the description and
    the code must agree character for character - which is why a separate test pins exactly
    that.
    """
    findings = engine.check_integrity(
        depending_skill(),
        delivery(SUBSTITUTED_BODY, url="http://127.0.0.1:8000/mock/registry/something/else"),
        invocation_id="inv_1",
    )

    assert findings == []


# --- Silence for everything that stands on nothing ------------------------------------


def test_a_skill_that_declares_no_component_raises_nothing(engine):
    """
    THE REASON EVERY OTHER SKILL IN THIS APP IS UNAFFECTED.

    Four weaknesses and the honest control skill declare no components at all, so the loop
    this check runs never has a single thing to iterate over. Their silence is structural -
    it does not depend on what they do, what they fetch, or what comes back.
    """
    plain = make_manifest(
        category="integration",
        capabilities=[
            {"id": "task.read", "scope": ["*"], "reason": "reads tasks"},
            {"id": "net.outbound", "scope": ["127.0.0.1"], "reason": "fetches things"},
        ],
    )

    # Even handed a delivery that would be a mismatch for anyone who had asked for one.
    findings = engine.check_integrity(plain, delivery(SUBSTITUTED_BODY), invocation_id="inv_1")

    assert findings == []
    assert engine.evaluate_install(plain) == []


# --- The check reads only what it is entitled to read ---------------------------------


def test_the_check_ignores_permissions_and_policy(engine):
    """
    A description that is over-privileged AND has a substituted component gets exactly one
    integrity finding from this check - not a different one, and not a louder one.

    The over-privilege is a real problem and is reported by a different question. This one
    neither knows nor cares. Keeping the inputs separate is what stops the five questions
    turning into five spellings of "something is wrong".
    """
    over_privileged = make_manifest(
        category="reporting",
        capabilities=[
            {"id": "task.read", "scope": ["*"], "reason": "reads tasks"},
            {"id": "net.outbound", "scope": ["*"], "reason": "anywhere at all"},
            {"id": "fs.write", "scope": ["*"], "reason": "writes anywhere"},
        ],
        dependencies=[
            {
                "name": "sizing-heuristics",
                "version": "2.3.1",
                "publisher": "Loft Analytics",
                "source": PACK_URL,
                "integrity": REVIEWED_PIN,
                "reason": "The sizing bands this skill applies.",
            }
        ],
    )

    findings = engine.check_integrity(
        over_privileged, delivery(SUBSTITUTED_BODY), invocation_id="inv_1"
    )

    assert types_of(findings) == ["COMPROMISED_DEPENDENCY"]


def test_two_wrong_components_are_two_separate_problems(engine):
    """
    Each component is judged on its own, and stays its own finding.

    A skill built on several things can be let down by more than one of them, and rolling
    those together would lose which one to go and fix.
    """
    manifest = make_manifest(
        category="integration",
        capabilities=[
            {"id": "net.outbound", "scope": ["127.0.0.1"], "reason": "fetches components"}
        ],
        dependencies=[
            {
                "name": "sizing-heuristics",
                "version": "2.3.1",
                "source": PACK_URL,
                "integrity": REVIEWED_PIN,
                "reason": "sizing bands",
            },
            {
                "name": "holiday-calendar",
                "version": "1.0.0",
                "source": "http://127.0.0.1:8000/mock/registry/holiday-calendar/1.0.0",
                "integrity": REVIEWED_PIN,
                "reason": "which days are working days",
            },
        ],
    )

    log = ObservationLog("inv_test")
    for url in [PACK_URL, "http://127.0.0.1:8000/mock/registry/holiday-calendar/1.0.0"]:
        log.record(
            capability="net.outbound",
            resource=url,
            detail={
                "method": "GET",
                "status": 200,
                "response_bytes": len(SUBSTITUTED_BODY.encode("utf-8")),
                "response_sha256": digest_of(SUBSTITUTED_BODY),
            },
        )

    findings = engine.check_integrity(manifest, log.entries(), invocation_id="inv_1")

    assert types_of(findings) == ["COMPROMISED_DEPENDENCY", "COMPROMISED_DEPENDENCY"]
    assert {f.dependency["name"] for f in findings} == {"sizing-heuristics", "holiday-calendar"}
    # Two different components, so two different problems - never merged into one.
    assert findings[0].dedup_key() != findings[1].dedup_key()
