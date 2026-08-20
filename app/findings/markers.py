"""
Writing the physical evidence that something happened.

When the app notices a security problem it leaves a small file behind on disk. That
file is the proof: you can point at it, open it, and read exactly what happened,
without needing the app running or the web pages open.

Every marker contains the phrase INTENTIONALLY_VULNERABLE_LAB_MARKER, so a single
search across the computer finds all of them at once - useful both for reviewing an
exercise and for cleaning up afterwards. Deleting the folder resets everything.

WHO WRITES THESE. The app writes them, never the skill. A skill announcing its own
misbehaviour would be weak evidence - and would mean giving skills a permission they
have no other reason to hold. The app only writes a marker when it has itself
observed the problem, so a marker existing is proof in its own right.

Specification references: feature spec sections 3.10 and 9.4; TDD section 8;
decisions D-12 and S-10; requirements FR-7.1 and FR-7.5.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.config import get_settings
from app.monitor.observations import Observation
from app.storage import atomic
from app.storage.models import Finding
from app.storage.store import now_iso

logger = logging.getLogger("taskbot.findings")

# The phrase every marker contains, so they can all be found with one search.
MARKER_PHRASE = "INTENTIONALLY_VULNERABLE_LAB_MARKER"


def _safe_for_filename(text: str) -> str:
    """
    Make a piece of text safe to use in a filename.

    In: any text. Out: the same text with awkward characters replaced by dashes.

    Timestamps contain colons, which Windows does not allow in filenames, so this is
    not merely cosmetic.
    """
    return re.sub(r"[^A-Za-z0-9_.-]", "-", text)


def write_marker(finding: Finding, observation: Observation | None = None) -> Path:
    """
    Leave a piece of evidence on disk for one finding.

    In: the finding, and the specific thing the skill did that caused it.
    Out: where the evidence was written.

    Called only when a problem is seen for the FIRST time. A problem happening again
    increases a counter on the existing finding rather than scattering near-identical
    files across the folder (decision S-10).
    """
    settings = get_settings()
    settings.markers_dir.mkdir(parents=True, exist_ok=True)

    filename = "-".join(
        [
            _safe_for_filename(now_iso()),
            _safe_for_filename(finding.skill_id),
            _safe_for_filename(finding.type),
        ]
    )
    path = settings.markers_dir / f"{filename}.json"

    contents = {
        "schema_version": 1,
        # First, and unmissable: what this file is.
        "marker": MARKER_PHRASE,
        "written_at": now_iso(),
        "finding_id": finding.id,
        "finding_type": finding.type,
        "ast_id": finding.ast_id,
        "ast_name": finding.ast_name,
        "severity": finding.severity,
        "skill_id": finding.skill_id,
        "skill_version": finding.skill_version,
        "invocation_id": finding.invocation_id,
        # Which AI model was in charge. Part of the evidence: "the assistant chose to
        # run this" only means something if you know which assistant.
        "model": finding.model,
        "summary": finding.summary,
        "observation": observation.model_dump() if observation else None,
    }

    atomic.write_json_atomic(path, contents)
    logger.info("Wrote evidence for %s to %s", finding.type, path.name)
    return path


def count_markers() -> int:
    """
    How many pieces of evidence are currently on disk.

    In: nothing. Out: the count.
    """
    markers_dir = get_settings().markers_dir
    if not markers_dir.exists():
        return 0
    return len([path for path in markers_dir.iterdir() if path.is_file()])
