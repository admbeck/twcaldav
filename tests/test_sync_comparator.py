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
    """A CalDAV note must not make an otherwise identical task look changed."""

    def test_plain_note_is_ignored(self, comparator) -> None:
        """TW title equals CalDAV summary; a note on CalDAV is not a difference."""
        tw_task = Task(
            uuid="test-uuid",
            description="Hepatologist appointment",
            status="pending",
            entry=datetime(2025, 9, 6, 15, 24, 30),
        )
        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Hepatologist appointment",
            status="NEEDS-ACTION",
            description="Ezgu Niat clinic",
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is True

    def test_note_plus_matching_annotations_is_equal(self, comparator) -> None:
        """Note in front of an annotation block that matches TW is equal."""
        tw_task = Task(
            uuid="test-uuid",
            description="Title",
            status="pending",
            entry=datetime(2025, 9, 6, 15, 24, 30),
            annotations=[{"entry": "20241117T103000Z", "description": "First"}],
        )
        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Title",
            status="NEEDS-ACTION",
            description=(
                "A note\n--- TaskWarrior Annotations ---\n20241117T103000Z|First"
            ),
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is True

    def test_note_plus_different_annotations_is_not_equal(self, comparator) -> None:
        """Differing annotations are still a real difference."""
        tw_task = Task(
            uuid="test-uuid",
            description="Title",
            status="pending",
            entry=datetime(2025, 9, 6, 15, 24, 30),
            annotations=[{"entry": "20241117T103000Z", "description": "First"}],
        )
        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Title",
            status="NEEDS-ACTION",
            description=(
                "A note\n--- TaskWarrior Annotations ---\n20241117T103000Z|Other"
            ),
        )

        assert comparator.tasks_content_equal(tw_task, caldav_todo) is False

    def test_imported_task_with_note_converges(self, comparator) -> None:
        """Regression: import of a todo with a note must compare equal afterwards.

        Previously the note became the TW description, so the pair never
        compared equal and was re-imported on every sync.
        """
        from twcaldav.field_mapper import caldav_to_taskwarrior

        caldav_todo = VTodo(
            uid="test-cd-uid",
            summary="Hepatologist appointment",
            status="NEEDS-ACTION",
            description="Ezgu Niat clinic",
            created=datetime(2025, 9, 6, 15, 24, 30),
            last_modified=datetime(2025, 9, 7, 8, 0, 0),
        )

        imported = caldav_to_taskwarrior(caldav_todo)

        assert comparator.tasks_content_equal(imported, caldav_todo) is True
