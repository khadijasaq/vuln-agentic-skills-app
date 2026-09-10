"""
Checks for the safe file saving code (app/storage/atomic.py).

Three things must hold:
  - saving is all-or-nothing, and leaves no temporary rubbish behind;
  - two things updating the same file at once never lose an update;
  - a missing or damaged file never stops the app.

Covers: feature spec section 4.1, decisions S-11, S-12, S-13.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from app.storage import atomic


# --- Basic reading and writing ---------------------------------------------------


def test_write_then_read_returns_the_same_value(tmp_path: Path):
    """The simplest promise: what we save is what we get back."""
    target = tmp_path / "thing.json"
    atomic.write_json_atomic(target, {"hello": "world", "count": 3})

    assert atomic.read_json(target, default=None) == {"hello": "world", "count": 3}


def test_writing_creates_missing_folders(tmp_path: Path):
    """Saving into a folder that does not exist yet just works."""
    target = tmp_path / "deep" / "nested" / "thing.json"
    atomic.write_json_atomic(target, [1, 2, 3])

    assert target.exists()
    assert atomic.read_json(target, default=None) == [1, 2, 3]


def test_no_temporary_files_are_left_behind(tmp_path: Path):
    """
    The temporary file used during saving must be renamed away, not left lying
    around. Stray ".tmp" files would clutter the data folder and confuse anyone
    inspecting the lab.
    """
    target = tmp_path / "thing.json"
    atomic.write_json_atomic(target, {"a": 1})

    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp." in p.name]
    assert leftovers == []


def test_overwriting_replaces_the_whole_file(tmp_path: Path):
    """A second save fully replaces the first - no leftovers from the old content."""
    target = tmp_path / "thing.json"
    atomic.write_json_atomic(target, {"first": "a much longer original value"})
    atomic.write_json_atomic(target, {"second": "x"})

    assert atomic.read_json(target, default=None) == {"second": "x"}


# --- Missing and damaged files ---------------------------------------------------


def test_missing_file_returns_the_fallback(tmp_path: Path):
    """Reading a file that was never created returns the fallback, without error."""
    assert atomic.read_json(tmp_path / "nothing-here.json", default=[]) == []


def test_corrupt_file_is_moved_aside_and_the_fallback_is_used(tmp_path: Path):
    """
    A damaged file must not stop the lab (decision S-13).

    The broken content is preserved under a ".corrupt." name so it can be inspected,
    and the caller simply receives the fallback value.
    """
    target = tmp_path / "broken.json"
    target.write_text("{this is not valid json at all", encoding="utf-8")

    result = atomic.read_json(target, default={"fresh": True})

    assert result == {"fresh": True}
    # The original file has been moved out of the way...
    assert not target.exists()
    # ...and kept, rather than destroyed.
    saved_copies = [p for p in tmp_path.iterdir() if ".corrupt." in p.name]
    assert len(saved_copies) == 1
    assert "not valid json" in saved_copies[0].read_text(encoding="utf-8")


def test_reading_a_damaged_file_never_raises(tmp_path: Path):
    """
    Whatever is wrong with the file, reading it must not throw an error upwards.
    This is what guarantees "the lab always starts".
    """
    for content in ["", "   ", "null-ish nonsense", "\x00\x01\x02"]:
        target = tmp_path / "bad.json"
        target.write_bytes(content.encode("utf-8", errors="ignore"))
        # Must not raise.
        atomic.read_json(target, default=[])


# --- Changing a file safely ------------------------------------------------------


def test_mutate_json_saves_the_changes(tmp_path: Path):
    """Editing inside the "with" block is written back automatically."""
    target = tmp_path / "list.json"
    atomic.write_json_atomic(target, [])

    with atomic.mutate_json(target, default=[]) as items:
        items.append("added")

    assert atomic.read_json(target, default=None) == ["added"]


def test_mutate_json_starts_from_the_fallback_when_the_file_is_missing(tmp_path: Path):
    """A first-ever edit works even though there is no file yet."""
    target = tmp_path / "brand-new.json"

    with atomic.mutate_json(target, default={"items": []}) as data:
        data["items"].append(1)

    assert atomic.read_json(target, default=None) == {"items": [1]}


def test_concurrent_updates_do_not_lose_any_writes(tmp_path: Path):
    """
    THE LOCKING TEST (decision S-12).

    Twenty workers each add ten numbers to the same file at the same time. If the
    lock works, all two hundred numbers survive. Without it, workers would overwrite
    each other and numbers would go missing.
    """
    target = tmp_path / "counter.json"
    atomic.write_json_atomic(target, [])

    workers = 20
    additions_each = 10

    def add_numbers(worker_index: int) -> None:
        for step in range(additions_each):
            with atomic.mutate_json(target, default=[]) as items:
                items.append(worker_index * 1000 + step)

    threads = [threading.Thread(target=add_numbers, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    saved = atomic.read_json(target, default=[])
    assert len(saved) == workers * additions_each
    # Every value must be unique, proving nothing was overwritten.
    assert len(set(saved)) == workers * additions_each


def test_saved_file_is_readable_plain_json(tmp_path: Path):
    """
    The saved file must be ordinary, human-readable JSON. People inspecting the lab
    read these files directly, so they must not need special tooling.
    """
    target = tmp_path / "thing.json"
    atomic.write_json_atomic(target, {"nested": {"value": [1, 2]}})

    raw = target.read_text(encoding="utf-8")
    assert json.loads(raw) == {"nested": {"value": [1, 2]}}
    assert "\n" in raw  # indented across multiple lines, not one long jumble
