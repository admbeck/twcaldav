"""Tests for the three-way merge of TaskWarrior tasks and CalDAV todos."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from twcaldav.caldav_client import VTodo
from twcaldav.field_mapper import (
    caldav_to_taskwarrior,
    note_entry,
    taskwarrior_to_caldav,
)
from twcaldav.sync_comparator import TaskComparator
from twcaldav.sync_merge import (
    build_merged_task,
    decode_base,
    encode_base,
    merge_snapshots,
    snapshot_from_task,
    snapshot_from_todo,
    snapshots_differ,
)
from twcaldav.taskwarrior import Task

ENTRY = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)


@pytest.fixture
def task() -> Task:
    """A synced pending task with a note, an annotation and a tag."""
    return Task(
        uuid="tw-uuid",
        description="Pay rent",
        status="pending",
        entry=ENTRY,
        modified=datetime(2026, 1, 2, 9, 0, 0, tzinfo=UTC),
        project="home",
        due=datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC),
        priority="M",
        tags=["money"],
        annotations=[
            {"entry": note_entry(ENTRY), "description": "Account 123"},
            {"entry": "20260101T100000Z", "description": "asked landlord"},
        ],
        caldav_uid="cd-uid",
    )


@pytest.fixture
def todo(task: Task) -> VTodo:
    """The CalDAV todo twcaldav writes for the task fixture."""
    return taskwarrior_to_caldav(task)


class TestSnapshot:
    """Tests for building snapshots."""

    def test_task_and_its_todo_have_equal_snapshots(
        self, task: Task, todo: VTodo
    ) -> None:
        """A task and the todo written from it snapshot identically."""
        assert snapshot_from_task(task) == snapshot_from_todo(todo)

    def test_snapshot_separates_note_from_annotations(self, task: Task) -> None:
        """The note annotation is the note field, not an annotation."""
        snapshot = snapshot_from_task(task)

        assert snapshot["note"] == "Account 123"
        assert snapshot["annotations"] == [["20260101T100000Z", "asked landlord"]]

    def test_todo_priority_is_bucketed(self, todo: VTodo) -> None:
        """CalDAV priorities in the same TaskWarrior bucket are equal."""
        todo.priority = 4

        assert snapshot_from_todo(todo)["priority"] == "M"

    def test_end_is_ignored_unless_completed(self, task: Task) -> None:
        """An end timestamp on a pending task is not part of the snapshot."""
        task.end = datetime(2026, 1, 3, 9, 0, 0, tzinfo=UTC)

        assert snapshot_from_task(task)["end"] is None

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("description", "Pay rent today"),
            ("status", "completed"),
            ("due", datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)),
            ("scheduled", datetime(2026, 1, 20, 12, 0, 0, tzinfo=UTC)),
            ("wait", datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)),
            ("priority", "H"),
            ("tags", ["money", "urgent"]),
            ("annotations", [{"entry": note_entry(ENTRY), "description": "Other"}]),
        ],
    )
    def test_snapshots_agree_with_comparator(
        self, task: Task, todo: VTodo, field: str, value: object
    ) -> None:
        """Snapshots differ exactly when the comparator sees a change."""
        setattr(task, field, value)

        content_equal = TaskComparator().tasks_content_equal(task, todo)

        assert content_equal == (snapshot_from_task(task) == snapshot_from_todo(todo))
        assert not content_equal


class TestSnapshotTimezones:
    """Tests for snapshots of times that carry a timezone."""

    def test_aware_todo_matches_the_task_built_from_it(self, todo: VTodo) -> None:
        """A Tashkent due and the UTC task due imported from it are equal."""
        todo.due = datetime(2025, 8, 15, 12, 30, 1, tzinfo=ZoneInfo("Asia/Tashkent"))
        task = Task.from_dict(caldav_to_taskwarrior(todo).to_dict())

        assert snapshot_from_task(task) == snapshot_from_todo(todo)
        assert snapshot_from_todo(todo)["due"] == "2025-08-15T07:30:01"


class TestBaseEncoding:
    """Tests for storing the base in the caldav_base UDA."""

    def test_round_trip(self, task: Task) -> None:
        """An encoded snapshot decodes to the same snapshot."""
        snapshot = snapshot_from_task(task)

        assert decode_base(encode_base(snapshot)) == snapshot

    @pytest.mark.parametrize("text", [None, "", "not json", '{"v": 99}', "[1, 2]"])
    def test_unusable_base_decodes_to_none(self, text: str | None) -> None:
        """Missing, corrupt or unknown-version bases are ignored."""
        assert decode_base(text) is None


class TestMergeSnapshots:
    """Tests for the per-field merge."""

    def _snapshots(self, task: Task) -> tuple[dict, dict, dict]:
        base = snapshot_from_task(task)
        return base, dict(base), dict(base)

    def test_unchanged(self, task: Task) -> None:
        """Nothing changed on either side: the base comes back."""
        base, tw, cd = self._snapshots(task)

        merged, conflicts = merge_snapshots(base, tw, cd, tw_newer=True)

        assert merged == base
        assert conflicts == []

    def test_taskwarrior_change_wins(self, task: Task) -> None:
        """A field changed only in TaskWarrior takes the TaskWarrior value."""
        base, tw, cd = self._snapshots(task)
        tw["due"] = "2026-03-01T12:00:00"

        merged, _ = merge_snapshots(base, tw, cd, tw_newer=False)

        assert merged["due"] == "2026-03-01T12:00:00"

    def test_caldav_change_wins(self, task: Task) -> None:
        """A field changed only in CalDAV takes the CalDAV value."""
        base, tw, cd = self._snapshots(task)
        cd["due"] = "2026-03-01T12:00:00"

        merged, _ = merge_snapshots(base, tw, cd, tw_newer=True)

        assert merged["due"] == "2026-03-01T12:00:00"

    def test_changes_to_different_fields_both_survive(self, task: Task) -> None:
        """TaskWarrior's priority and CalDAV's due date are both kept."""
        base, tw, cd = self._snapshots(task)
        tw["priority"] = "H"
        cd["due"] = "2026-03-01T12:00:00"

        merged, conflicts = merge_snapshots(base, tw, cd, tw_newer=True)

        assert merged["priority"] == "H"
        assert merged["due"] == "2026-03-01T12:00:00"
        assert conflicts == []

    def test_same_change_on_both_sides_is_not_a_conflict(self, task: Task) -> None:
        """Both sides setting the same value agree."""
        base, tw, cd = self._snapshots(task)
        tw["title"] = cd["title"] = "Pay rent now"

        merged, conflicts = merge_snapshots(base, tw, cd, tw_newer=False)

        assert merged["title"] == "Pay rent now"
        assert conflicts == []

    @pytest.mark.parametrize(("tw_newer", "expected"), [(True, "TW"), (False, "CD")])
    def test_conflict_goes_to_newer_side(
        self, task: Task, tw_newer: bool, expected: str
    ) -> None:
        """The same field changed differently takes the newer side's value."""
        base, tw, cd = self._snapshots(task)
        tw["title"] = "TW"
        cd["title"] = "CD"

        merged, conflicts = merge_snapshots(base, tw, cd, tw_newer=tw_newer)

        assert merged["title"] == expected
        assert conflicts == ["title"]

    def test_note_removed_in_taskwarrior(self, task: Task) -> None:
        """Deleting the note in TaskWarrior deletes it from the merge."""
        base, tw, cd = self._snapshots(task)
        tw["note"] = ""

        merged, _ = merge_snapshots(base, tw, cd, tw_newer=False)

        assert merged["note"] == ""

    def test_annotations_added_on_both_sides(self, task: Task) -> None:
        """Annotations added independently on each side are all kept."""
        base, tw, cd = self._snapshots(task)
        tw["annotations"] = [*base["annotations"], ["20260105T000000Z", "tw"]]
        cd["annotations"] = [*base["annotations"], ["20260106T000000Z", "cd"]]

        merged, conflicts = merge_snapshots(base, tw, cd, tw_newer=True)

        assert merged["annotations"] == [
            ["20260101T100000Z", "asked landlord"],
            ["20260105T000000Z", "tw"],
            ["20260106T000000Z", "cd"],
        ]
        assert conflicts == []

    def test_annotation_removed_on_one_side(self, task: Task) -> None:
        """An annotation removed on one side is removed from the merge."""
        base, tw, cd = self._snapshots(task)
        tw["annotations"] = []
        cd["annotations"] = [*base["annotations"], ["20260106T000000Z", "cd"]]

        merged, _ = merge_snapshots(base, tw, cd, tw_newer=False)

        assert merged["annotations"] == [["20260106T000000Z", "cd"]]

    def test_tags_are_merged_as_sets(self, task: Task) -> None:
        """A tag removed on one side and added on the other both apply."""
        base, tw, cd = self._snapshots(task)
        tw["tags"] = []
        cd["tags"] = ["money", "urgent"]

        merged, _ = merge_snapshots(base, tw, cd, tw_newer=False)

        assert merged["tags"] == ["urgent"]

    def test_missing_end_takes_the_other_side(self, task: Task) -> None:
        """A client that omits COMPLETED doesn't clear the completion time."""
        task.status = "completed"
        task.end = datetime(2026, 1, 3, 9, 0, 0, tzinfo=UTC)
        base, tw, cd = self._snapshots(task)
        cd["end"] = None

        merged, conflicts = merge_snapshots(base, tw, cd, tw_newer=False)

        assert merged["end"] == "2026-01-03T09:00:00"
        assert conflicts == []

    def test_reopened_task_drops_end(self, task: Task) -> None:
        """Reopening a completed task clears the completion time."""
        task.status = "completed"
        task.end = datetime(2026, 1, 3, 9, 0, 0, tzinfo=UTC)
        base, tw, cd = self._snapshots(task)
        tw["status"] = "NEEDS-ACTION"
        tw["end"] = None

        merged, _ = merge_snapshots(base, tw, cd, tw_newer=False)

        assert merged["status"] == "NEEDS-ACTION"
        assert merged["end"] is None


class TestSnapshotsDiffer:
    """Tests for deciding whether a side needs a write."""

    def test_equal(self, task: Task) -> None:
        """Equal snapshots don't differ."""
        snapshot = snapshot_from_task(task)

        assert not snapshots_differ(snapshot, dict(snapshot))

    def test_missing_end_is_not_a_difference(self, task: Task) -> None:
        """A side without a completion time doesn't need one written."""
        task.status = "completed"
        task.end = datetime(2026, 1, 3, 9, 0, 0, tzinfo=UTC)
        snapshot = snapshot_from_task(task)

        assert not snapshots_differ(snapshot, {**snapshot, "end": None})

    def test_other_field(self, task: Task) -> None:
        """Any other changed field is a difference."""
        snapshot = snapshot_from_task(task)

        assert snapshots_differ(snapshot, {**snapshot, "title": "x"})


class TestBuildMergedTask:
    """Tests for turning a merged snapshot into a TaskWarrior task."""

    def test_takes_caldav_values_and_keeps_taskwarrior_data(
        self, task: Task, todo: VTodo
    ) -> None:
        """CalDAV-side changes apply, TaskWarrior-only data is kept."""
        task.extra = {"depends": ["other-uuid"]}
        todo.due = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        merged = snapshot_from_todo(todo)

        result = build_merged_task(task, todo, merged)

        assert result.due == datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        assert result.uuid == "tw-uuid"
        assert result.project == "home"
        assert result.extra == {"depends": ["other-uuid"]}
        assert task.due == datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)

    def test_snapshot_of_result_is_the_merge(self, task: Task, todo: VTodo) -> None:
        """The built task snapshots to exactly the merged snapshot."""
        merged = snapshot_from_task(task)
        merged["title"] = todo.summary = "Pay rent today"
        merged["note"] = ""
        merged["annotations"] = [*merged["annotations"], ["20260106T000000Z", "cd"]]
        merged["tags"] = ["money", "urgent"]

        result = build_merged_task(task, todo, merged)

        assert snapshot_from_task(result) == merged

    def test_stores_merge_as_base(self, task: Task, todo: VTodo) -> None:
        """The built task carries the merge as its new base."""
        merged = snapshot_from_task(task)

        result = build_merged_task(task, todo, merged)

        assert decode_base(result.caldav_base) == merged

    def test_completing_from_caldav(self, task: Task, todo: VTodo) -> None:
        """A todo completed in CalDAV completes the task."""
        todo.status = "COMPLETED"
        todo.completed = datetime(2026, 1, 3, 9, 0, 0, tzinfo=UTC)
        merged = snapshot_from_todo(todo)

        result = build_merged_task(task, todo, merged)

        assert result.status == "completed"
        assert result.end == datetime(2026, 1, 3, 9, 0, 0, tzinfo=UTC)
