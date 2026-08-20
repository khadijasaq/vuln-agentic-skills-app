"""
Checks for the file channel (part of app/skills/context.py).

Two promises are tested here, and they work together:

  SAFETY    - a skill cannot reach files outside the app's own folders, cannot
              overwrite the app's records, and has no way to delete or move anything.
  DETECTION - every refused attempt is still written down, in its true position.

That combination is the point. A skill trying to read your private documents is
stopped, AND the attempt appears in the security report. Neither promise is traded
for the other.

Covers: feature spec section 7.3; decisions S-19, S-26, S-27; requirements FR-7.3
and FR-7.4; acceptance test A-8 (in part).
"""

from __future__ import annotations

import pytest

from app.monitor import audit_hook
from app.monitor.observations import ObservationLog
from app.skills.context import CapabilityRefused, FileBroker, SkillContext


@pytest.fixture(autouse=True)
def _watcher_installed():
    audit_hook.install_audit_hook()
    yield


@pytest.fixture
def running_skill(tmp_settings):
    """The stage set as if a skill were running."""
    notebook = ObservationLog("inv_test")
    context = SkillContext("inv_test", notebook)
    with audit_hook.invocation_scope("inv_test", notebook):
        yield context, notebook


def write_setup_file(path, content: str) -> None:
    """
    Create a file as part of a test's preparation.

    In: where and what. Out: nothing.

    Wrapped in the "this is the app, not the skill" marker, because otherwise the
    watcher would correctly record the TEST setting things up as though the pretend
    skill had done it. That is the watcher working properly, not a bug - the test
    just has to be honest about who is acting.
    """
    with audit_hook.broker_frame():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")



# --- Normal, allowed use ---------------------------------------------------------


def test_a_skill_can_read_a_file_inside_the_data_folder(running_skill, tmp_settings):
    """The allowed case works."""
    context, notebook = running_skill
    target = tmp_settings.data_dir / "notes.txt"
    write_setup_file(target, "hello from the data folder")

    content = context.files.read(str(target))

    assert content == "hello from the data folder"
    assert notebook.entries()[0].capability == "fs.read"
    assert notebook.entries()[0].outcome == "ok"


def test_reading_a_file_records_its_size_and_fingerprint(running_skill, tmp_settings):
    """Recorded so a later check can prove which data moved (decision S-8)."""
    context, notebook = running_skill
    target = tmp_settings.data_dir / "notes.txt"
    write_setup_file(target, "some content")

    context.files.read(str(target))

    detail = notebook.entries()[0].detail
    assert detail["bytes"] > 0
    assert len(detail["sha256"]) == 64


def test_a_skill_can_write_a_file_inside_the_data_folder(running_skill, tmp_settings):
    """Writing inside the allowed area is fine."""
    context, notebook = running_skill
    target = tmp_settings.data_dir / "scratch" / "output.txt"

    context.files.write(str(target), "written by a skill")

    assert target.read_text(encoding="utf-8") == "written by a skill"
    assert notebook.entries()[0].capability == "fs.write"


# --- Refusals: each one is BOTH blocked AND recorded -----------------------------


def test_reading_outside_the_allowed_folders_is_refused_and_recorded(running_skill, tmp_path):
    """
    THE CORE SAFETY CHECK.

    A skill reaching for somewhere it should not go is stopped - and the attempt is
    written down, so the security report shows exactly what it tried.
    """
    context, notebook = running_skill
    outside = tmp_path / "somewhere-else" / "private.txt"
    write_setup_file(outside, "private")

    with pytest.raises(CapabilityRefused) as refusal:
        context.files.read(str(outside))

    assert refusal.value.reason == "path_outside_allowed_roots"
    record = notebook.entries()[0]
    assert record.outcome == "refused"
    assert record.refusal_reason == "path_outside_allowed_roots"


def test_climbing_out_with_dot_dot_is_refused(running_skill, tmp_settings):
    """
    A path like "data/../../../secrets.txt" looks harmless until you follow it.
    Working out where a path really leads BEFORE checking it is what catches this.
    """
    context, notebook = running_skill
    escaping = str(tmp_settings.data_dir / ".." / ".." / "escaped.txt")

    with pytest.raises(CapabilityRefused) as refusal:
        context.files.read(escaping)

    assert refusal.value.reason == "path_outside_allowed_roots"
    assert notebook.entries()[0].outcome == "refused"


def test_the_record_shows_what_the_skill_asked_for_not_where_it_led(running_skill, tmp_settings):
    """
    The report must show the skill's actual request. Showing the resolved location
    instead would hide the trick it was attempting.
    """
    context, notebook = running_skill
    asked_for = str(tmp_settings.data_dir / ".." / "escaped.txt")

    with pytest.raises(CapabilityRefused):
        context.files.read(asked_for)

    assert ".." in notebook.entries()[0].resource


def test_overwriting_the_apps_own_records_is_refused(running_skill, tmp_settings):
    """
    DECISION S-27.

    A skill that could overwrite the activity log or the findings file could erase
    the evidence of its own behaviour. Every record file is protected.
    """
    context, notebook = running_skill

    for protected in [
        tmp_settings.tasks_file,
        tmp_settings.installed_file,
        tmp_settings.findings_file,
        tmp_settings.activity_file,
    ]:
        with pytest.raises(CapabilityRefused) as refusal:
            context.files.write(str(protected), "erased")
        assert refusal.value.reason == "protected_state_file"

    assert all(entry.outcome == "refused" for entry in notebook.entries())


def test_writing_into_the_evidence_folder_is_refused(running_skill, tmp_settings):
    """
    The marker files are proof that something happened. A skill must not be able to
    forge or destroy them.
    """
    context, _ = running_skill
    marker = tmp_settings.markers_dir / "forged.json"

    with pytest.raises(CapabilityRefused) as refusal:
        context.files.write(str(marker), "forged evidence")

    assert refusal.value.reason == "protected_state_file"


def test_a_missing_file_is_an_error_not_a_refusal(running_skill, tmp_settings):
    """
    Asking for a file that is not there is a mistake, not an attack, and the record
    says so.
    """
    context, notebook = running_skill

    with pytest.raises(CapabilityRefused):
        context.files.read(str(tmp_settings.data_dir / "not-here.txt"))

    assert notebook.entries()[0].outcome == "error"


def test_a_refusal_keeps_its_place_in_the_sequence(running_skill, tmp_settings, tmp_path):
    """
    DECISION S-26.

    A refused request stays exactly where it happened in the order of events. If it
    were moved to the end, anything reading the sequence would see a false story.
    """
    context, notebook = running_skill
    allowed = tmp_settings.data_dir / "fine.txt"
    write_setup_file(allowed, "fine")

    context.files.read(str(allowed))
    with pytest.raises(CapabilityRefused):
        context.files.read(str(tmp_path / "outside.txt"))
    context.files.read(str(allowed))

    entries = notebook.entries()
    assert len(entries) == 3
    assert entries[1].outcome == "refused"
    assert entries[1].seq == 2


# --- What is deliberately not offered --------------------------------------------


def test_there_is_no_way_to_delete_or_move_a_file():
    """
    REQUIREMENT FR-7.4.

    Deleting, moving and changing permissions are simply not offered. A skill that
    wants them has to go around the app - which the process-wide watcher catches.
    """
    for forbidden in ["delete", "remove", "unlink", "move", "rename", "chmod"]:
        assert not hasattr(FileBroker, forbidden)


def test_there_is_no_way_to_start_another_program():
    """Starting programs is deliberately absent from the official channel (D-4)."""
    from app.skills.context import SkillContext as Context

    assert not hasattr(Context, "proc")
