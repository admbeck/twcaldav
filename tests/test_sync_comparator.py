"""Tests for the sync comparator module."""

from datetime import datetime

import pytest

from twcaldav.caldav_client import VTodo
from twcaldav.sync_comparator import TaskComparator
from twcaldav.taskwarrior import Task


@pytest.fixture
def comparator():
    """Create a TaskComparator instance."""
    return TaskComparator()


class TestTasksContentEqualCompleted:
    """Tests for completed task comparison, specifically end/completed timestamps."""

    def test_completed_both_have_matching_timestamps(self, comparator) -> None:
        """Both tasks have matching completion timestamps - should be equal."""
        completed_time = datetime(2025, 11, 21, 8, 8, 18)

        tw_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="completed",
            entry=datetime(2025, 9, 6, 15, 24, 30),
            modified=completed_time,
            end=completed_time,
        )

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Test task",
            status="COMPLETED",
            completed=completed_time,
            last_modified=completed_time,
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is True

    def test_completed_both_have_different_timestamps(self, comparator) -> None:
        """Both tasks have different completion timestamps - should NOT be equal."""
        tw_end = datetime(2025, 11, 21, 8, 8, 18)
        cd_completed = datetime(2025, 11, 22, 10, 0, 0)

        tw_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="completed",
            entry=datetime(2025, 9, 6, 15, 24, 30),
            modified=tw_end,
            end=tw_end,
        )

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Test task",
            status="COMPLETED",
            completed=cd_completed,
            last_modified=cd_completed,
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is False

    def test_completed_tw_has_end_caldav_missing_completed(self, comparator) -> None:
        """TW has end timestamp, CalDAV lacks COMPLETED - should be equal.

        This is the key fix: CalDAV todos with COMPLETED status often lack
        the COMPLETED timestamp property. We should NOT treat this as a
        content difference since the status already indicates completion.
        """
        tw_end = datetime(2025, 11, 21, 8, 8, 18)

        tw_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="completed",
            entry=datetime(2025, 9, 6, 15, 24, 30),
            modified=tw_end,
            end=tw_end,
        )

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Test task",
            status="COMPLETED",
            completed=None,  # No COMPLETED timestamp
            last_modified=datetime(2025, 11, 21, 8, 8, 18),
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is True

    def test_completed_caldav_has_completed_tw_missing_end(self, comparator) -> None:
        """CalDAV has COMPLETED timestamp, TW lacks end - should be equal.

        Edge case: TW should always have end for completed tasks, but if
        somehow it doesn't, we should still treat this as equal since both
        have completed status.
        """
        cd_completed = datetime(2025, 11, 21, 8, 8, 18)

        tw_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="completed",
            entry=datetime(2025, 9, 6, 15, 24, 30),
            modified=datetime(2025, 11, 21, 8, 8, 18),
            end=None,  # No end timestamp
        )

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Test task",
            status="COMPLETED",
            completed=cd_completed,
            last_modified=cd_completed,
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is True

    def test_completed_both_missing_timestamps(self, comparator) -> None:
        """Both tasks are completed but neither has a timestamp - should be equal."""
        tw_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="completed",
            entry=datetime(2025, 9, 6, 15, 24, 30),
            modified=datetime(2025, 11, 21, 8, 8, 18),
            end=None,
        )

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Test task",
            status="COMPLETED",
            completed=None,
            last_modified=datetime(2025, 11, 21, 8, 8, 18),
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is True


class TestTasksContentEqualPending:
    """Tests for pending task comparison."""

    def test_pending_tasks_identical(self, comparator) -> None:
        """Identical pending tasks should be equal."""
        now = datetime(2025, 11, 21, 8, 8, 18)

        tw_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="pending",
            entry=now,
            modified=now,
        )

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Test task",
            status="NEEDS-ACTION",
            last_modified=now,
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is True

    def test_pending_tasks_different_description(self, comparator) -> None:
        """Pending tasks with different descriptions should NOT be equal."""
        now = datetime(2025, 11, 21, 8, 8, 18)

        tw_task = Task(
            uuid="test-uuid",
            description="Task A",
            status="pending",
            entry=now,
            modified=now,
        )

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Task B",
            status="NEEDS-ACTION",
            last_modified=now,
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is False

    def test_pending_tasks_different_status(self, comparator) -> None:
        """Tasks with different status should NOT be equal."""
        now = datetime(2025, 11, 21, 8, 8, 18)

        tw_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="pending",
            entry=now,
            modified=now,
        )

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Test task",
            status="COMPLETED",
            last_modified=now,
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is False


class TestTasksContentEqualDueDates:
    """Tests for due date comparison."""

    def test_matching_due_dates(self, comparator) -> None:
        """Tasks with matching due dates should be equal."""
        now = datetime(2025, 11, 21, 8, 8, 18)
        due = datetime(2025, 12, 1, 12, 0, 0)

        tw_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="pending",
            entry=now,
            modified=now,
            due=due,
        )

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Test task",
            status="NEEDS-ACTION",
            due=due,
            last_modified=now,
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is True

    def test_different_due_dates(self, comparator) -> None:
        """Tasks with different due dates should NOT be equal."""
        now = datetime(2025, 11, 21, 8, 8, 18)

        tw_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="pending",
            entry=now,
            modified=now,
            due=datetime(2025, 12, 1, 12, 0, 0),
        )

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Test task",
            status="NEEDS-ACTION",
            due=datetime(2025, 12, 5, 12, 0, 0),
            last_modified=now,
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is False

    def test_one_has_due_date_other_missing(self, comparator) -> None:
        """Tasks where one has due date and other doesn't should NOT be equal."""
        now = datetime(2025, 11, 21, 8, 8, 18)

        tw_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="pending",
            entry=now,
            modified=now,
            due=datetime(2025, 12, 1, 12, 0, 0),
        )

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Test task",
            status="NEEDS-ACTION",
            due=None,
            last_modified=now,
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is False


class TestTasksContentEqualNotes:
    """The CalDAV note is compared against the TW note annotation."""

    ENTRY = datetime(2025, 9, 6, 15, 24, 30)
    NOTE_TS = "20250906T152429Z"

    def _tw(self, annotations: list[dict] | None = None) -> Task:
        return Task(
            uuid="test-uuid",
            description="Title",
            status="pending",
            entry=self.ENTRY,
            annotations=annotations,
        )

    def _cd(self, description: str | None) -> VTodo:
        return VTodo(
            uid="test-cd-uid",
            summary="Title",
            status="NEEDS-ACTION",
            description=description,
        )

    def test_same_note_is_equal(self, comparator) -> None:
        """TW note annotation matching the CalDAV note is equal."""
        tw_task = self._tw([{"entry": self.NOTE_TS, "description": "A note"}])

        assert comparator.tasks_content_equal(tw_task, self._cd("A note")) is True

    def test_different_note_is_not_equal(self, comparator) -> None:
        """A changed note is a real difference."""
        tw_task = self._tw([{"entry": self.NOTE_TS, "description": "A note"}])

        assert comparator.tasks_content_equal(tw_task, self._cd("Other")) is False

    def test_line_endings_and_whitespace_are_ignored(self, comparator) -> None:
        """CRLF vs LF and surrounding whitespace do not count as a change."""
        tw_task = self._tw([{"entry": self.NOTE_TS, "description": "a\nb"}])

        assert comparator.tasks_content_equal(tw_task, self._cd(" a\r\nb\n")) is True

    def test_legacy_task_without_note_annotation_differs(self, comparator) -> None:
        """A task synced before notes were imported needs one update."""
        assert comparator.tasks_content_equal(self._tw(), self._cd("A note")) is False

    def test_note_plus_matching_annotations_is_equal(self, comparator) -> None:
        """Note and annotation block both matching TW is equal."""
        tw_task = self._tw(
            [
                {"entry": self.NOTE_TS, "description": "A note"},
                {"entry": "20241117T103000Z", "description": "First"},
            ]
        )
        caldav_todo = self._cd(
            "A note\n--- TaskWarrior Annotations ---\n20241117T103000Z|First"
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is True

    def test_note_plus_different_annotations_is_not_equal(self, comparator) -> None:
        """Differing annotations are still a real difference."""
        tw_task = self._tw(
            [
                {"entry": self.NOTE_TS, "description": "A note"},
                {"entry": "20241117T103000Z", "description": "First"},
            ]
        )
        caldav_todo = self._cd(
            "A note\n--- TaskWarrior Annotations ---\n20241117T103000Z|Other"
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is False

    def test_imported_task_with_note_converges(self, comparator) -> None:
        """Regression: a freshly imported todo with a note compares equal."""
        from twcaldav.field_mapper import caldav_to_taskwarrior

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Hepatologist appointment",
            status="NEEDS-ACTION",
            description="Ezgu Niat clinic",
            created=self.ENTRY,
            last_modified=datetime(2025, 9, 7, 8, 0, 0),
        )

        imported = caldav_to_taskwarrior(caldav_todo)

        assert comparator.tasks_content_equal(imported, caldav_todo) is True

    def test_legacy_task_converges_after_one_import(self, comparator) -> None:
        """After one CalDAV -> TW update the legacy task compares equal."""
        from twcaldav.field_mapper import caldav_to_taskwarrior

        legacy = self._tw()
        caldav_todo = self._cd("A note")

        updated = caldav_to_taskwarrior(caldav_todo, existing_task=legacy)

        assert comparator.tasks_content_equal(updated, caldav_todo) is True


class TestTasksContentEqualAnnotationFormats:
    """Annotations are compared by timestamp and text, not by block format."""

    ENTRY = datetime(2025, 9, 6, 15, 24, 30)

    def _tw(self) -> Task:
        return Task(
            uuid="test-uuid",
            description="Title",
            status="pending",
            entry=self.ENTRY,
            annotations=[
                {"entry": "20241117T103000Z", "description": "First\nsecond line"},
            ],
        )

    def _cd(self, description: str) -> VTodo:
        return VTodo(
            uid="test-cd-uid",
            summary="Title",
            status="NEEDS-ACTION",
            description=description,
        )

    def test_readable_block_is_equal(self, comparator) -> None:
        """The readable format matching TW annotations is equal."""
        caldav_todo = self._cd(
            "Taskwarrior annotations:\n[2024-11-17 10:30:00 UTC] First\n  second line"
        )

        assert comparator.tasks_content_equal(self._tw(), caldav_todo) is True

    def test_readable_block_with_other_text_is_not_equal(self, comparator) -> None:
        """Different annotation text is a real difference."""
        caldav_todo = self._cd(
            "Taskwarrior annotations:\n[2024-11-17 10:30:00 UTC] Something else"
        )

        assert comparator.tasks_content_equal(self._tw(), caldav_todo) is False

    def test_legacy_block_is_equal(self, comparator) -> None:
        """A todo still in the old pipe format does not count as changed."""
        tw_task = Task(
            uuid="test-uuid",
            description="Title",
            status="pending",
            entry=self.ENTRY,
            annotations=[{"entry": "20241117T103000Z", "description": "First"}],
        )
        caldav_todo = self._cd(
            "--- TaskWarrior Annotations ---\n20241117T103000Z|First"
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is True
