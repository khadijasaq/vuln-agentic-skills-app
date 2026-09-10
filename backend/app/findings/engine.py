"""
The part that decides whether a skill did something wrong.

It answers two questions - deliberately different questions, asked of deliberately
different information:

  TRUTHFULNESS    "Did it do what it said it would?"
                  Compares WHAT IT DID against WHAT IT DECLARED.

  PROPORTIONALITY "Did it need that much power in the first place?"
                  Compares WHAT IT ASKED FOR against WHAT ITS KIND OF SKILL NEEDS.

A skill can fail either one without failing the other. It can be modest and lying
(fails the first only). It can be sweeping and completely honest (fails the second
only). That is exactly why the two are separate checks reading separate inputs - if
they were two thresholds on one comparison they would blur together, and telling the
different kinds of vulnerability apart would become impossible.

CORRELATION     "Did it combine two harmless abilities into a harmful one?"
                Reads ONLY the ordered notebook of what happened - not the
                declaration and not the category. Reading the task list is fine;
                sending data locally is fine; reading it and THEN sending it is theft.

That third question is answered independently of the other two, on purpose: a skill
can be perfectly honest and perfectly modest and still steal by combining abilities,
so correlation must never be built on top of the truthfulness check (invariant I-7).

PROVENANCE      "Where did the behaviour come from?"
                Reads what came BACK from the network, and what the skill did after.

INTEGRITY       "Is what arrived what was agreed?"
                Compares the component a skill SAID it depends on against the
                fingerprint of the component that was actually delivered. The only
                question here where the skill itself has done nothing wrong.

THIS FILE IS DELIBERATELY PURE. It takes information in, works out an answer, and
hands it back. It reads no files, writes nothing, and never asks the AI model
anything. That is what makes "the honest skill produces no findings" a guarantee
rather than a hope: the same evidence always gives the same answer.

Specification references: feature spec section 9; TDD section 4; invariants I-6 and
I-7.
"""

from __future__ import annotations

from typing import Any, Literal

from app.findings.baselines import Baseline
from app.findings.taxonomy import TAXONOMY, FindingType
from app.monitor.observations import Observation, digest_of
from app.skills.manifest import Manifest, Vocabulary
from app.skills.scope import ScopeMatcher, resolve_self_url
from app.storage.models import Finding
from app.storage.store import new_id, now_iso


# How long a piece of text has to be before we will treat "it appeared in the reply and
# then in what the skill did" as meaningful rather than as a coincidence.
#
# Short words collide constantly. A document containing "open" and a skill that later
# touches something called "open" have nothing to do with each other, and reporting that
# as evidence would bury the real findings in noise - and would make an honest skill that
# fetches anything at all look guilty. Twelve characters is long enough to exclude the
# accidental and short enough that any web address, file path or sentence still counts.
MIN_INFLUENCE_LENGTH = 12

# Parts of a record that describe what came BACK from a request rather than what the
# skill asked for. They are skipped when looking for a steered action: they are not
# something the skill chose, so finding a match there would prove nothing.
RESPONSE_DETAIL_PREFIX = "response_"


class FindingsEngine:
    """
    Works out which security problems a skill's behaviour reveals.

    It is created with the shared capability list and the yardstick policy, and then
    simply answers questions. It holds no changing state of its own.
    """

    def __init__(self, vocabulary: Vocabulary, baselines: dict[str, Baseline]) -> None:
        self._vocabulary = vocabulary
        self._baselines = baselines

    # --- Question 1: did it do what it said? -------------------------------------

    def check_truthfulness(
        self,
        manifest: Manifest,
        observations: list[Observation],
        *,
        invocation_id: str | None = None,
        activity_id: str | None = None,
        model: str | None = None,
    ) -> list[Finding]:
        """
        Compare what a skill actually did against what it declared.

        In: the skill's description, everything it did, and details for the record.
        Out: a list of problems found (empty if it behaved as promised).

        Note that refused attempts are judged exactly like successful ones. Wanting
        to do something undeclared is the security event; whether the app happened to
        stop it is a separate matter.
        """
        findings: list[Finding] = []

        for observation in observations:
            # Going around the official channel is its own kind of problem, and is
            # reported whether or not the capability was declared. It is a deliberate
            # act - the skill chose not to ask.
            if observation.source == "audit_hook":
                findings.append(
                    self._build(
                        "BROKER_BYPASS",
                        manifest,
                        observed=observation,
                        invocation_id=invocation_id,
                        activity_id=activity_id,
                        model=model,
                    )
                )

            declaration = self._declaration_for(manifest, observation.capability)

            if declaration is None:
                # It did something its description never mentions at all.
                findings.append(
                    self._build(
                        "UNDECLARED_CAPABILITY",
                        manifest,
                        observed=observation,
                        invocation_id=invocation_id,
                        activity_id=activity_id,
                        model=model,
                    )
                )
                continue

            # It declared this ability, but used it somewhere it said it would not.
            scope_kind = self._vocabulary.scope_kind(observation.capability)
            if not ScopeMatcher.matches(declaration.scope, observation.resource, scope_kind):
                findings.append(
                    self._build(
                        "SCOPE_VIOLATION",
                        manifest,
                        observed=observation,
                        declared_scope=declaration.scope,
                        invocation_id=invocation_id,
                        activity_id=activity_id,
                        model=model,
                    )
                )

        return findings

    # --- Question 2: did it need that much power? --------------------------------

    def check_proportionality(
        self,
        manifest: Manifest,
        *,
        trigger: Literal["install", "invocation"] = "invocation",
        invocation_id: str | None = None,
        activity_id: str | None = None,
        model: str | None = None,
    ) -> list[Finding]:
        """
        Compare what a skill asked for against what its kind of skill should need.

        In: the skill's description and details for the record.
        Out: a list of problems found.

        This looks ONLY at the description and the policy. It never looks at what the
        skill did - too much power is too much power whether or not it has been used
        yet, which is why this can be answered before a skill has ever run.
        """
        findings: list[Finding] = []
        baseline = self._baselines.get(manifest.category)

        if baseline is None:
            # A category with no yardstick cannot be judged. The manifest checks
            # already refuse skills like this, so reaching here means something is
            # wrong upstream, not that the skill is safe.
            return findings

        for declaration in manifest.capabilities:
            if declaration.id not in baseline.allowed:
                findings.append(
                    self._build(
                        "EXCESSIVE_GRANT",
                        manifest,
                        granted={
                            "capability": declaration.id,
                            "scope": declaration.scope,
                            "reason": "capability_outside_baseline",
                            "allowed": baseline.allowed,
                        },
                        trigger=trigger,
                        invocation_id=invocation_id,
                        activity_id=activity_id,
                        model=model,
                    )
                )
                continue

            limit = baseline.limit_for(declaration.id)
            scope_kind = self._vocabulary.scope_kind(declaration.id)
            if ScopeMatcher.is_broader_than(declaration.scope, limit, scope_kind):
                findings.append(
                    self._build(
                        "EXCESSIVE_GRANT",
                        manifest,
                        granted={
                            "capability": declaration.id,
                            "scope": declaration.scope,
                            "reason": "scope_broader_than_baseline",
                            "limit": limit,
                        },
                        trigger=trigger,
                        invocation_id=invocation_id,
                        activity_id=activity_id,
                        model=model,
                    )
                )

        return findings

    def check_unused_grants(
        self,
        manifest: Manifest,
        capabilities_used_recently: set[str],
        invocation_count: int,
        window: int,
        *,
        model: str | None = None,
    ) -> list[Finding]:
        """
        Look for power a skill holds but has never actually used.

        In: the skill's description, which abilities it has used lately, how many
        times it has run, and how many runs count as "lately".
        Out: a list of problems found.

        We wait until a skill has run several times before judging this. Otherwise a
        brand new skill would be accused of not using an ability it simply has not
        needed yet.
        """
        if invocation_count < window:
            return []

        findings: list[Finding] = []
        for declaration in manifest.capabilities:
            if declaration.id not in capabilities_used_recently:
                findings.append(
                    self._build(
                        "UNUSED_GRANT",
                        manifest,
                        granted={"capability": declaration.id, "scope": declaration.scope},
                        model=model,
                    )
                )
        return findings

    # --- Question 3: did it combine two harmless abilities into a harmful one? ----

    def check_correlation(
        self,
        manifest: Manifest,
        observations: list[Observation],
        *,
        invocation_id: str | None = None,
        activity_id: str | None = None,
        model: str | None = None,
    ) -> list[Finding]:
        """
        Look for the user's data being read and then sent out in the same run.

        In: the skill's description, everything it did in order, and details for the
        record. Out: a list of problems found.

        This is the third and last question, and it is unlike the other two: it does
        not care one bit what the skill declared or what its category allows. Reading
        the task list is fine. Sending something to a local address is fine. Reading
        the task list and THEN sending it somewhere is theft - and that is true no
        matter how honestly the skill described itself. So this method reads ONLY the
        notebook of what happened; the description is passed in only to stamp on the
        finished finding, never to decide anything (invariant I-7).

        How it decides: it lines up every "read the tasks" against every "send data
        out" that happened AFTER it, and compares their fingerprints. It is like
        comparing fingerprints to see whether the same tasks that were read are the
        ones that got sent out. A match on even one item is enough, because sending
        even part of the user's private list is theft.

        Two deliberate details, both load-bearing:
          - the send must come AFTER the read (a later line number). Sending data and
            only then reading the tasks is not this problem;
          - a send that was refused still counts. The fingerprint of what it wanted to
            send was written down before the app said no, so wanting to steal is caught
            even when nothing left the machine (invariant I-3).
        """
        findings: list[Finding] = []

        reads = [
            observation
            for observation in observations
            if observation.capability == "task.read" and observation.outcome == "ok"
        ]
        # Any outcome - a refused send still carries the fingerprint of what it meant
        # to send, and intent is what this question is about.
        sends = [
            observation
            for observation in observations
            if observation.capability == "net.outbound"
        ]

        for sent in sends:
            sent_items = set(sent.detail.get("item_digests") or [])
            if not sent_items:
                # Nothing recognisable from the task list is inside this send (for
                # example a bare "you have 3 tasks left" summary carries no task
                # fingerprints), so there is nothing to steal here.
                continue

            matched: set[str] = set()
            first_read_seq: int | None = None
            for read in reads:
                if read.seq >= sent.seq:
                    # Only a read that happened BEFORE this send can have been the
                    # source of what was sent.
                    continue
                overlap = set(read.detail.get("item_digests") or []) & sent_items
                if overlap:
                    matched |= overlap
                    # reads are already in the order they happened, so the first one
                    # we find that matches is the earliest source.
                    if first_read_seq is None:
                        first_read_seq = read.seq

            if matched:
                findings.append(
                    self._build(
                        "COVERT_DATA_FLOW",
                        manifest,
                        correlation={
                            "observation_seqs": [first_read_seq, sent.seq],
                            "matched_items": len(matched),
                        },
                        evidence_seq=sent.seq,
                        invocation_id=invocation_id,
                        activity_id=activity_id,
                        model=model,
                    )
                )

        return findings

    # --- Question 4: whose idea was this? ----------------------------------------

    def check_provenance(
        self,
        manifest: Manifest,
        observations: list[Observation],
        *,
        returned_summary: str | None = None,
        invocation_id: str | None = None,
        activity_id: str | None = None,
        model: str | None = None,
    ) -> list[Finding]:
        """
        Look for a skill being told what to do by something it fetched.

        In: the skill's description, everything it did in order, and what it handed back
        to the assistant. Out: a list of problems found.

        This is the fourth and last question, and it is the mirror image of the third.
        Correlation watches the user's data going OUT. This watches instructions coming
        IN. Fetching a document is fine. Sending a message is fine. Fetching a document
        and then doing what the document says is a skill that is no longer under the
        control of anyone who reviewed it - and that is true no matter how honest its
        description is, how modest its permissions are, or whether anything was stolen.

        It reads only two things: the ordered notebook, and what came back from the
        network. It never looks at the description or the category - those belong to the
        other questions, and keeping them out is what stops this becoming a re-telling of
        one of them (invariant I-7). The description is passed in only to stamp on the
        finished finding.

        Two different problems are looked for:

          A STEERED ACTION   something the skill did afterwards - where it sent data, or
                             a value it sent - is a piece of text that was sitting in the
                             fetched reply. The fetched content chose it.

          A RELAY            a line from the fetched reply appears, word for word, in
                             what the skill told the assistant. Text from outside has
                             reached the assistant's own context.

        What this deliberately does NOT claim: that the assistant then DID what that text
        said. Whether a model obeys is not something the same evidence always answers, and
        this file must always give the same answer to the same evidence. So the relay is
        reported - the words arrived - and obedience is left as something a person can see
        on the activity screen, never as a finding.

        Two details, both load-bearing:
          - the steered action must come AFTER the fetch (a later line number);
          - a refused action still counts. Where it was told to send is evidence even if
            the app then refused to send it.
        """
        findings: list[Finding] = []

        # Only a request that actually came back with something can have steered
        # anything. A refused or failed request has no reply, and carries no response
        # fields at all.
        sources = [
            observation
            for observation in observations
            if observation.capability == "net.outbound"
            and observation.detail.get("response_item_digests")
        ]

        for source in sources:
            source_digests = set(source.detail.get("response_item_digests") or [])

            findings.extend(
                self._steered_actions(
                    manifest,
                    observations,
                    source,
                    source_digests,
                    invocation_id=invocation_id,
                    activity_id=activity_id,
                    model=model,
                )
            )

            relay = self._relayed_line(
                manifest,
                source,
                returned_summary,
                invocation_id=invocation_id,
                activity_id=activity_id,
                model=model,
            )
            if relay is not None:
                findings.append(relay)

        return findings

    def _steered_actions(
        self,
        manifest: Manifest,
        observations: list[Observation],
        source: Observation,
        source_digests: set[str],
        *,
        invocation_id: str | None,
        activity_id: str | None,
        model: str | None,
    ) -> list[Finding]:
        """
        Find things the skill did afterwards that came out of the fetched reply.

        In: the description, the notebook, the fetch, the fingerprints of what came back,
        and details for the record. Out: any problems found.

        We compare fingerprints rather than text, which is the same trick used to prove
        stolen data moved: a web address in the reply and the web address the skill then
        used produce the identical fingerprint, so a match is proof they are the same
        thing - without having to guess how the skill got from one to the other.
        """
        findings: list[Finding] = []

        for acted in observations:
            if acted.seq <= source.seq:
                # Only something that happened AFTER the reply arrived can have been
                # steered by it. Acting first and fetching later is not this problem.
                continue

            matched = self._influenced_value(acted, source_digests)
            if matched is None:
                continue

            influence, value = matched
            findings.append(
                self._build(
                    "EXTERNAL_INSTRUCTION_FLOW",
                    manifest,
                    provenance={
                        "source_seq": source.seq,
                        "acted_seq": acted.seq,
                        "source_url": source.resource,
                        "influence": influence,
                        "matched_digest": digest_of(value),
                        "matched_excerpt": value[:200],
                    },
                    evidence_seq=acted.seq,
                    invocation_id=invocation_id,
                    activity_id=activity_id,
                    model=model,
                )
            )

        return findings

    def _influenced_value(
        self, acted: Observation, source_digests: set[str]
    ) -> tuple[str, str] | None:
        """
        Work out whether one action was chosen by the fetched reply.

        In: the line describing what the skill did, and the fingerprints of what came
        back. Out: a pair - which part was steered, and the text itself - or nothing.

        Where it sent things is checked first, because it is the most serious and the
        most legible: "the document chose the destination" is the whole story in one
        sentence.
        """
        if self._is_influenced(acted.resource, source_digests):
            return "resource", acted.resource

        for key, value in acted.detail.items():
            # Skip the parts of the record that describe what came BACK. The skill did
            # not choose those, so a match there would prove nothing about its behaviour.
            if key.startswith(RESPONSE_DETAIL_PREFIX):
                continue
            if isinstance(value, str) and self._is_influenced(value, source_digests):
                return "parameter", value

        return None

    @staticmethod
    def _is_influenced(value: str, source_digests: set[str]) -> bool:
        """
        Did this exact piece of text come out of the fetched reply?

        In: the text, and the fingerprints of what came back. Out: True or False.

        Anything too short to be meaningful is rejected before comparing, so a common
        word shared by coincidence never becomes evidence.
        """
        if not isinstance(value, str) or len(value) < MIN_INFLUENCE_LENGTH:
            return False
        return digest_of(value) in source_digests

    def _relayed_line(
        self,
        manifest: Manifest,
        source: Observation,
        returned_summary: str | None,
        *,
        invocation_id: str | None,
        activity_id: str | None,
        model: str | None,
    ) -> Finding | None:
        """
        Look for a line of the fetched reply repeated in what the skill told the assistant.

        In: the description, the fetch, what the skill handed back, and details for the
        record. Out: one problem, or nothing.

        Unlike the steered-action check this compares the words themselves, not their
        fingerprints, because the question is different: not "is this the same thing?"
        but "does this sentence appear INSIDE that longer sentence?". A fingerprint
        cannot answer that.

        The pieces of text were collected from the WHOLE reply when it arrived, not from
        the shortened readable copy kept for evidence - so a long document cannot hide an
        instruction past the end of the excerpt.

        At most one finding per fetch. A document that plants three lines is one act of
        putting words in the assistant's mouth, not three.
        """
        if not returned_summary:
            return None

        # The pieces of text arrive longest first, so the finding quotes the most
        # convincing match rather than the first short one that happens to fit.
        for text in source.detail.get("response_strings") or []:
            if len(text) < MIN_INFLUENCE_LENGTH:
                continue
            if text in returned_summary:
                return self._build(
                    "AGENT_INSTRUCTION_RELAY",
                    manifest,
                    provenance={
                        "source_seq": source.seq,
                        "acted_seq": None,
                        "source_url": source.resource,
                        "influence": "returned_summary",
                        "matched_digest": digest_of(text),
                        "matched_excerpt": text[:200],
                    },
                    evidence_seq=source.seq,
                    invocation_id=invocation_id,
                    activity_id=activity_id,
                    model=model,
                )

        return None

    # --- Question 5: is what arrived what was agreed? -----------------------------

    def check_integrity(
        self,
        manifest: Manifest,
        observations: list[Observation] | None = None,
        *,
        trigger: Literal["install", "invocation"] = "invocation",
        invocation_id: str | None = None,
        activity_id: str | None = None,
        model: str | None = None,
    ) -> list[Finding]:
        """
        Look for a skill being handed a different component than the one it expected.

        In: the skill's description, everything it did in order (if it has run yet), and
        details for the record. Out: a list of problems found.

        This is the fifth question, and it is unlike the other four in one way that is
        worth stating plainly: the skill has done nothing wrong. Its description is true.
        Its permissions are the right size. It stole nothing and obeyed nobody. It even
        wrote down which exact build of somebody else's component it expected. Somebody
        else swapped that component, and no amount of inspecting the skill would show it.

        An analogy: the skill ordered a specific part, quoted the part number, and checked
        the box when it arrived. The box has the right label on the outside and something
        else inside. The person who ordered it is not the problem.

        Two problems are looked for:

          NO FINGERPRINT PINNED  the skill named a component but never said what it should
                                 look like. Nothing that arrives can be checked at all.
                                 Answerable from the description alone, so it is asked
                                 even before the skill has ever run.

          A DIFFERENT BUILD      the skill DID say what it should look like, something was
                                 delivered, and the two do not match.

        What this reads, and what it deliberately does not: it reads the skill's declared
        components and the fingerprint the app recorded when something was delivered. It
        never reads which permissions were declared, never reads the category yardstick,
        never reads what was sent out, and - importantly - never reads what the delivered
        component actually SAYS. Whether the content is malicious is a different question
        belonging to a different check. This one asks only whether the bytes are the
        agreed bytes, which is why a perfectly harmless substitution is still reported.

        Two details, both load-bearing:
          - only a SUCCESSFUL delivery is compared. A refused request never arrived, and a
            reply that was an error ("no such component") is not a build of anything - it
            has a fingerprint, but comparing it to the pin would report a compromise every
            time the registry was simply empty;
          - with no declared component there is nothing to compare, so this is silent for
            every skill that does not stand on anything - which is all of them but one.
        """
        findings: list[Finding] = []

        for dependency in manifest.dependencies:
            described = {
                "name": dependency.name,
                "version": dependency.version,
                "source": dependency.source,
                "publisher": dependency.publisher,
            }

            if dependency.integrity is None:
                # Nothing was promised, so nothing can be checked. This is visible from
                # the description alone and needs no delivery to have happened.
                findings.append(
                    self._build(
                        "UNPINNED_DEPENDENCY",
                        manifest,
                        dependency={
                            **described,
                            "declared_integrity": None,
                            "delivered_integrity": None,
                            "acquired_seq": None,
                            "reason": "no_pin_declared",
                        },
                        trigger=trigger,
                        invocation_id=invocation_id,
                        activity_id=activity_id,
                        model=model,
                    )
                )
                # With no promise there is no comparison to make, so we are done with
                # this component.
                continue

            pinned = dependency.integrity.split(":", 1)[1]

            for acquired in self._deliveries_of(dependency, observations or []):
                delivered = acquired.detail.get("response_sha256")
                if delivered == pinned:
                    # Exactly what was promised. Nothing to report - and this is the case
                    # that proves the check can stay quiet.
                    continue

                findings.append(
                    self._build(
                        "COMPROMISED_DEPENDENCY",
                        manifest,
                        dependency={
                            **described,
                            "declared_integrity": dependency.integrity,
                            "delivered_integrity": f"sha256:{delivered}",
                            "delivered_bytes": acquired.detail.get("response_bytes"),
                            "acquired_seq": acquired.seq,
                            "reason": "digest_mismatch",
                        },
                        evidence_seq=acquired.seq,
                        trigger=trigger,
                        invocation_id=invocation_id,
                        activity_id=activity_id,
                        model=model,
                    )
                )

        return findings

    @staticmethod
    def _deliveries_of(dependency, observations: list[Observation]) -> list[Observation]:
        """
        Find the times this particular component was actually delivered.

        In: one declared component, and the notebook of what the skill did.
        Out: the lines describing a successful delivery of it.

        Matching is on the address, exactly as written. That is deliberate: the skill
        says where it gets the component from, and it must be the same place it actually
        went. A near-match would be a guess, and a guess is not evidence.

        The __SELF_URL__ placeholder in dependency.source is resolved to the deployed
        base URL before comparing, so the check works on any platform.
        """
        deliveries: list[Observation] = []
        resolved_source = resolve_self_url(dependency.source)

        for observation in observations:
            if observation.capability != "net.outbound":
                continue
            if observation.resource != resolved_source:
                continue
            # A reply that never arrived, or that was an error page rather than the
            # component, is not a delivery. Treating one as a delivery would report a
            # compromise every time the component was merely missing.
            if observation.detail.get("status") != 200:
                continue
            if not observation.detail.get("response_sha256"):
                continue
            deliveries.append(observation)

        return deliveries

    # --- Putting it together ------------------------------------------------------

    def evaluate_invocation(
        self,
        manifest: Manifest,
        observations: list[Observation],
        *,
        invocation_id: str,
        activity_id: str | None = None,
        model: str | None = None,
        returned_summary: str | None = None,
    ) -> list[Finding]:
        """
        Run every applicable check after one skill run.

        In: the skill's description, everything it did, and details for the record.
        Out: every problem found, truthfulness first.
        """
        findings = self.check_truthfulness(
            manifest,
            observations,
            invocation_id=invocation_id,
            activity_id=activity_id,
            model=model,
        )
        findings.extend(
            self.check_proportionality(
                manifest,
                trigger="invocation",
                invocation_id=invocation_id,
                activity_id=activity_id,
                model=model,
            )
        )
        findings.extend(
            self.check_correlation(
                manifest,
                observations,
                invocation_id=invocation_id,
                activity_id=activity_id,
                model=model,
            )
        )
        findings.extend(
            self.check_provenance(
                manifest,
                observations,
                returned_summary=returned_summary,
                invocation_id=invocation_id,
                activity_id=activity_id,
                model=model,
            )
        )
        findings.extend(
            self.check_integrity(
                manifest,
                observations,
                trigger="invocation",
                invocation_id=invocation_id,
                activity_id=activity_id,
                model=model,
            )
        )
        return findings

    def evaluate_install(self, manifest: Manifest, *, model: str | None = None) -> list[Finding]:
        """
        Check a skill at the moment it is switched on, before it has ever run.

        In: the skill's description. Out: any problems visible from the description
        alone.

        Two questions can be answered here, and both for the same reason: they are about
        what the skill CLAIMS, not about what it does.

          "Did it need that much power?"        - the whole question.
          "Is what arrived what was agreed?"    - only the half that asks whether the
                                                  skill promised anything at all. Whether
                                                  a delivery matched cannot be asked
                                                  before there has been a delivery, and
                                                  no delivery has happened yet, so that
                                                  half is structurally silent here.

        The remaining questions all need behaviour to compare against.
        """
        findings = self.check_proportionality(manifest, trigger="install", model=model)
        findings.extend(self.check_integrity(manifest, trigger="install", model=model))
        return findings

    # --- Internal helpers ---------------------------------------------------------

    def _declaration_for(self, manifest: Manifest, capability_id: str):
        """
        Find what a skill declared about one ability.

        In: the description and the ability. Out: the declaration, or nothing.
        """
        for declaration in manifest.capabilities:
            if declaration.id == capability_id:
                return declaration
        return None

    def _build(
        self,
        type_id: str,
        manifest: Manifest,
        *,
        observed: Observation | None = None,
        granted: dict[str, Any] | None = None,
        correlation: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        dependency: dict[str, Any] | None = None,
        declared_scope: list[str] | None = None,
        evidence_seq: int | None = None,
        trigger: Literal["install", "invocation"] = "invocation",
        invocation_id: str | None = None,
        activity_id: str | None = None,
        model: str | None = None,
    ) -> Finding:
        """
        Assemble one finding.

        In: which kind of problem, the skill's description, and whatever evidence
        applies. Out: the finished finding.

        Which evidence field is filled tells a reader which question the finding
        answers - "observed" for truthfulness, "granted" for proportionality,
        "correlation" for a combination problem, "provenance" for an instruction
        problem, "dependency" for a supply-chain one - so the different kinds can be
        told apart without reading the wording.

        For a combination problem there is no single "observed" line, because the
        problem is a pair of lines - a read and a later send. So "observed" is left
        empty and "evidence_seq" points at the send, which is the line the evidence
        marker is written against.
        """
        finding_type: FindingType = TAXONOMY[type_id]
        stamp = now_iso()

        summary = self._describe(finding_type, observed, granted, declared_scope, dependency)

        return Finding(
            id=new_id("fnd"),
            type=finding_type.id,
            ast_id=finding_type.ast_id,
            ast_name=finding_type.ast_name,
            axis=finding_type.axis,
            severity=finding_type.severity,
            skill_id=manifest.id,
            skill_version=manifest.version,
            trigger=trigger,
            invocation_id=invocation_id,
            activity_id=activity_id,
            model=model,
            declared={
                "capabilities": [
                    declaration.model_dump() for declaration in manifest.capabilities
                ],
                "category": manifest.category,
            },
            observed=observed.model_dump() if observed else None,
            granted=granted,
            correlation=correlation,
            provenance=provenance,
            dependency=dependency,
            summary=summary,
            evidence={
                "observation_seq": observed.seq if observed else evidence_seq,
                "marker": None,
            },
            first_seen=stamp,
            last_seen=stamp,
            occurrences=1,
        )

    def _describe(
        self,
        finding_type: FindingType,
        observed: Observation | None,
        granted: dict[str, Any] | None,
        declared_scope: list[str] | None,
        dependency: dict[str, Any] | None = None,
    ) -> str:
        """
        Turn a problem into a readable sentence.

        In: the type and whatever evidence there is. Out: a sentence.

        If anything is missing we fall back to the raw template rather than failing -
        a slightly clumsy sentence is much better than losing the finding.

        Every kind of evidence contributes its own words to the same pot, and each
        template picks out only the ones it uses. Adding a new kind therefore cannot
        change any sentence that was already being written.
        """
        values: dict[str, Any] = {
            "capability": (observed.capability if observed else (granted or {}).get("capability", "")),
            "resource": observed.resource if observed else "",
            "declared_scope": ", ".join(declared_scope) if declared_scope else "",
            "reason": (granted or {}).get("reason", ""),
            "name": (dependency or {}).get("name", ""),
            "version": (dependency or {}).get("version", ""),
            "source": (dependency or {}).get("source", ""),
        }
        try:
            return finding_type.summary_template.format(**values)
        except (KeyError, IndexError):
            return finding_type.summary_template
