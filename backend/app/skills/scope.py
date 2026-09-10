"""
Deciding whether something a skill touched falls inside the limits it declared.

A "scope" is the fine print on a permission. Declaring `fs.read` says "I read
files"; the scope says *which* files - for example `["data/notes/**"]`, meaning
anything inside the notes folder.

Two questions get asked of scopes, and they are used by two completely different
security checks:

  matches()          - "is this exact thing inside the limits it declared?"
                       Used when checking whether a skill told the truth.

  is_broader_than()  - "are these limits wider than a skill of this kind should
                       have?" Used when checking whether a skill is over-powered.

Specification references: feature spec section 6, decisions S-24, S-25 and S-35.
"""

from __future__ import annotations

import fnmatch
import os
import re
from urllib.parse import urlparse

# The two ways of writing "anywhere at all, no limit". Spotting these is how the
# over-powered check notices a skill that has been handed the keys to everything.
UNBOUNDED_PATTERNS = frozenset({"*", "**"})


def _host_of(value: str) -> str:
    """
    Get just the host part of something that might be a full web address.

    In: either a full address ("http://127.0.0.1:8000/x") or an already-plain host
    ("127.0.0.1"). Out: the host on its own ("127.0.0.1").

    A full address has a "://" in it; a plain host does not. For a plain host there is
    nothing to strip, so it comes straight back - which is why comparing two plain
    hosts (as the over-powered check does) is unaffected.
    """
    if "://" in value:
        return urlparse(value).hostname or value
    return value


_SELF_URL_PLACEHOLDER = "__SELF_URL__"


def resolve_self_url(value: str) -> str:
    """
    Replace the __SELF_URL__ placeholder in a string with the deployed base URL.

    In: a string that may contain __SELF_URL__. Out: the string with the placeholder
    replaced, or the original string if the placeholder is absent or TASKBOT_SELF_URL
    is not set.

    This lets manifests and hub documents reference the deployed address without
    hardcoding a hostname. Locally, TASKBOT_SELF_URL defaults to http://127.0.0.1:PORT,
    so the placeholder resolves to the same address the skill would have used anyway.
    On Render, it resolves to the platform-assigned URL.
    """
    if _SELF_URL_PLACEHOLDER not in value:
        return value
    self_url = os.environ.get("TASKBOT_SELF_URL", "")
    if not self_url:
        return value
    return value.replace(_SELF_URL_PLACEHOLDER, self_url)


def resolve_self_url_recursive(value):
    """
    Recursively replace __SELF_URL__ in any data structure (str, list, dict).

    In: anything. Out: the same structure with __SELF_URL__ replaced in all strings.
    Non-string leaves are returned unchanged.
    """
    if isinstance(value, str):
        return resolve_self_url(value)
    if isinstance(value, list):
        return [resolve_self_url_recursive(item) for item in value]
    if isinstance(value, dict):
        return {key: resolve_self_url_recursive(val) for key, val in value.items()}
    return value


def get_collector_url(params: dict | None = None) -> str:
    """
    Get the URL where stolen data should be sent.

    In: skill params (may contain _self_url). Out: the collector URL.

    When TASKBOT_COLLECTOR_URL is set (e.g. on Render with ngrok), skills send
    stolen data to that external URL so it actually reaches the attacker's machine.
    When not set (local development), skills send to the built-in mock collector
    on this machine.
    """
    external = os.environ.get("TASKBOT_COLLECTOR_URL", "")
    if external:
        return external
    base_url = ""
    if params:
        base_url = params.get("_self_url") or ""
    if not base_url:
        base_url = os.environ.get("TASKBOT_SELF_URL", "http://127.0.0.1:8000")
    return f"{base_url}/mock/collector"


class ScopeMatcher:
    """
    All the scope questions in one place.

    These are plain functions grouped under a name for readability - the class holds
    no information of its own.
    """

    @staticmethod
    def matches(scope: list[str], resource: str, scope_kind: str) -> bool:
        """
        Is this particular thing inside the declared limits?

        In:
          scope      - the declared limits, e.g. ["data/notes/**"];
          resource   - the actual thing touched, e.g. "data/notes/plan.txt";
          scope_kind - what sort of thing it is (a file path, a website address...).
        Out: True if it is inside the limits.

        An empty list of limits means nothing is allowed, which is the safe reading:
        a skill that declared no limits at all has not been granted anything.
        """
        if not scope:
            return False

        # "none" means the capability has no official channel at all - there is no
        # such thing as being "inside the limits", so nothing ever matches. Merely
        # doing it is the thing worth reporting.
        if scope_kind == "none":
            return False

        for pattern in scope:
            if ScopeMatcher._one_pattern_matches(pattern, resource, scope_kind):
                return True
        return False

    @staticmethod
    def _one_pattern_matches(pattern: str, resource: str, scope_kind: str) -> bool:
        """
        Compare one limit pattern against one actual thing.

        In: the pattern, the thing, and what sort of thing it is. Out: True/False.
        """
        # "Anywhere at all" matches everything, whatever the kind.
        if pattern in UNBOUNDED_PATTERNS:
            return True

        if scope_kind == "path_glob":
            return ScopeMatcher._path_matches(pattern, resource)

        if scope_kind == "host_glob":
            # A host limit is about WHICH COMPUTER, not which exact address. A skill
            # records a full web address when it sends something (for example
            # "http://127.0.0.1:8000/mock/collector"), but the limit it declared is a
            # plain host ("127.0.0.1"). So we compare hosts to hosts: pull the host out
            # of the address first, then match. Comparing the whole address against a
            # plain host would never match, and would wrongly accuse an honestly
            # declared local send of going somewhere it did not declare.
            #
            # Website addresses are not case sensitive, so EXAMPLE.COM and example.com
            # are the same place.
            #
            # The special pattern "__SELF_URL__" matches the app's own deployed
            # hostname, read from the TASKBOT_SELF_URL environment variable. This
            # lets manifests and baselines reference the deployed address without
            # hardcoding a hostname.
            if pattern == "__SELF_URL__":
                import os
                from urllib.parse import urlparse as _urlparse
                self_url = os.environ.get("TASKBOT_SELF_URL", "")
                if self_url:
                    try:
                        deployed_host = (_urlparse(self_url).hostname or "").lower()
                        if deployed_host and _host_of(resource).lower() == deployed_host:
                            return True
                    except Exception:
                        pass
                # Fall through: also match localhost since self_url defaults there
                return fnmatch.fnmatch(_host_of(resource).lower(), "127.0.0.1")
            return fnmatch.fnmatch(_host_of(resource).lower(), pattern.lower())

        # Task names and setting names are compared exactly as written.
        return fnmatch.fnmatchcase(resource, pattern)

    @staticmethod
    def _path_matches(pattern: str, path: str) -> bool:
        """
        Compare a file-path limit against an actual file path.

        In: the pattern and the path. Out: True/False.

        File paths need their own rule because the two star forms mean different
        things, and getting this wrong would quietly widen every permission:

          *     matches within ONE folder level  - "data/*.txt" is not "data/a/b.txt"
          **    matches ACROSS folder levels     - "data/**" is anything under data
          /**   at the end also matches the folder itself, so "data/**" covers the
                bare path "data" as well as everything inside it (decision S-35).
                This is how gitignore and most other glob tools behave, and it is
                what a person writing "data/**" plainly means.
        """
        pattern = pattern.replace("\\", "/")
        path = path.replace("\\", "/")

        # Build a precise text-matching rule from the pattern, one piece at a time,
        # so that "*" and "**" get genuinely different treatment.
        regex_parts: list[str] = []
        index = 0
        while index < len(pattern):
            character = pattern[index]

            # "/**" is handled as a single unit, because the slash in front of it
            # has to become optional - that is what lets "data/**" match "data".
            if character == "/" and pattern.startswith("/**", index):
                index += 3  # step over the "/**"
                if index < len(pattern) and pattern[index] == "/":
                    # Middle of a pattern, e.g. "data/**/notes.txt". The whole
                    # "/**" part may be absent, so "data/notes.txt" matches too.
                    index += 1
                    regex_parts.append("(?:/.*)?/")
                else:
                    # End of the pattern, e.g. "data/**". Matches the folder itself
                    # and anything at any depth beneath it.
                    regex_parts.append("(?:/.*)?")
                continue

            if character == "*":
                if pattern.startswith("**", index):
                    # A "**" not preceded by a slash, e.g. a pattern starting with
                    # "**/". It can match anything, slashes included.
                    index += 2
                    if index < len(pattern) and pattern[index] == "/":
                        index += 1
                        # "**/" should also match zero folders, so "**/x.txt"
                        # covers a plain "x.txt".
                        regex_parts.append("(?:.*/)?")
                    else:
                        regex_parts.append(".*")
                    continue
                # A single "*" stays inside one folder level.
                regex_parts.append("[^/]*")
                index += 1
                continue

            if character == "?":
                regex_parts.append("[^/]")
                index += 1
                continue

            # Anything else is an ordinary character, escaped so that dots and other
            # symbols are treated literally rather than as pattern syntax.
            regex_parts.append(re.escape(character))
            index += 1

        compiled = re.compile("^" + "".join(regex_parts) + "$")
        return compiled.match(path) is not None

    @staticmethod
    def is_unbounded(scope: list[str]) -> bool:
        """
        Do these limits actually mean "no limit"?

        In: the declared limits. Out: True if they mean "anywhere at all".

        Being unbounded is the clearest signal that a skill has more reach than it
        needs, so the over-powered check looks for exactly this.
        """
        return len(scope) == 1 and scope[0] in UNBOUNDED_PATTERNS

    @staticmethod
    def is_broader_than(scope: list[str], limit: list[str], scope_kind: str) -> bool:
        """
        Do these limits reach further than the yardstick allows?

        In:
          scope      - what the skill declared;
          limit      - the widest thing a skill of this kind should have;
          scope_kind - what sort of thing the limits describe.
        Out: True if the skill reaches further than it should.

        Three rules, in order:

        1. If the yardstick itself says "anywhere", nothing can exceed it.
        2. If the skill says "anywhere" but the yardstick does not, it is broader.
        3. Otherwise, each declared pattern must fit inside at least one allowed
           pattern. We check by testing the declared pattern as if it were a real
           thing - a rough but predictable test that never needs to imagine every
           possible file name.
        """
        if not scope:
            return False

        if ScopeMatcher.is_unbounded(limit):
            return False

        if ScopeMatcher.is_unbounded(scope):
            return True

        for pattern in scope:
            covered = any(
                ScopeMatcher._one_pattern_matches(allowed, pattern, scope_kind)
                for allowed in limit
            )
            if not covered:
                return True

        return False
