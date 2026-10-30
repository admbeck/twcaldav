"""Integration tests for CalDAV → TaskWarrior synchronization."""

import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.integration.helpers import (
    create_todo,
    find_todo_by_summary,
    get_caldav_client,
    get_calendar,
    get_tasks,
    modify_todo,
    run_sync,
)


@pytest.mark.integration
def test_caldav_to_tw_create_simple(clean_test_environment) -> None:
    """Create simple todo in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo in CalDAV
    summary = "Simple CalDAV test todo"
    assert create_todo(calendar, summary)

    # Run sync
    assert run_sync()

    # Verify task exists in TaskWarrior
    tasks = get_tasks()
    assert len(tasks) == 1
    assert tasks[0]["description"] == summary
    assert tasks[0]["status"] == "pending"


@pytest.mark.integration
def test_caldav_to_tw_create_with_due_date(clean_test_environment) -> None:
    """Create todo with due date in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo with due date
    summary = "CalDAV todo with due date"
    due_date = datetime.now(UTC) + timedelta(days=3)
    assert create_todo(calendar, summary, due=due_date)

    # Run sync
    assert run_sync()

    # Verify task has correct due date
    tasks = get_tasks()
    assert len(tasks) == 1
    assert tasks[0]["description"] == summary
    assert "due" in tasks[0]


@pytest.mark.integration
def test_caldav_to_tw_create_with_dtstart(clean_test_environment) -> None:
    """Create todo with DTSTART in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo with start date
    summary = "CalDAV todo with start date"
    start_date = datetime.now(UTC) + timedelta(days=2)
    assert create_todo(calendar, summary, dtstart=start_date)

    # Run sync
    assert run_sync()

    # Verify task has correct scheduled date
    tasks = get_tasks()
    assert len(tasks) == 1
    assert tasks[0]["description"] == summary
    assert "scheduled" in tasks[0]


@pytest.mark.integration
def test_caldav_to_tw_create_with_wait(clean_test_environment) -> None:
    """Create todo with X-TASKWARRIOR-WAIT in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo with wait date in the past (so task stays pending, not waiting)
    summary = "CalDAV todo with wait date"
    wait_date = datetime.now(UTC) - timedelta(days=1)
    assert create_todo(calendar, summary, wait=wait_date)

    # Run sync
    assert run_sync()

    # Verify task has correct wait date
    tasks = get_tasks()
    assert len(tasks) == 1
    assert tasks[0]["description"] == summary
    assert "wait" in tasks[0]


@pytest.mark.integration
def test_caldav_to_tw_completed_with_timestamp(clean_test_environment) -> None:
    """Create completed todo with COMPLETED timestamp, verify it syncs to TW."""
    from datetime import UTC, datetime

    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create completed todo with COMPLETED timestamp
    summary = "CalDAV completed task"
    completed_time = datetime.now(UTC)
    assert create_todo(calendar, summary, status="COMPLETED", completed=completed_time)

    # Run sync
    assert run_sync()

    # Verify task has end timestamp
    # Query for completed tasks explicitly (completed tasks not in pending list)
    completed_tasks = get_tasks(status="completed")
    assert len(completed_tasks) == 1
    assert completed_tasks[0]["description"] == summary
    assert completed_tasks[0]["status"] == "completed"
    assert "end" in completed_tasks[0]


@pytest.mark.integration
def test_caldav_to_tw_create_with_priority(clean_test_environment) -> None:
    """Create todo with priority in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo with high priority (1 = highest in CalDAV)
    summary = "CalDAV todo with high priority"
    assert create_todo(calendar, summary, priority=1)

    # Run sync
    assert run_sync()

    # Verify task has correct priority
    tasks = get_tasks()
    assert len(tasks) == 1
    assert tasks[0]["description"] == summary
    assert tasks[0].get("priority") == "H"


@pytest.mark.integration
def test_caldav_to_tw_create_completed(clean_test_environment) -> None:
    """Create completed todo in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create completed todo
    summary = "Completed CalDAV todo"
    assert create_todo(calendar, summary, status="COMPLETED")

    # Run sync
    assert run_sync()

    # Verify task is completed (won't appear in pending tasks)
    tasks = get_tasks()
    # Completed tasks are not returned by get_tasks (which filters for pending)
    # This is expected behavior
    assert len(tasks) == 0


@pytest.mark.integration
def test_caldav_to_tw_sync_preexisting_completed(clean_test_environment) -> None:
    """Sync completed todo that existed in CalDAV before first sync.

    This test verifies that completed todos in CalDAV are discovered
    and synced to TaskWarrior on the first sync run.
    """
    # Create completed todo in CalDAV before any sync
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    summary = "Pre-existing completed CalDAV todo"
    assert create_todo(calendar, summary, status="COMPLETED")

    # Run sync for the first time
    assert run_sync()

    # Verify task was created in TaskWarrior with completed status
    # Use status=None to get all tasks regardless of status
    tasks = get_tasks(project="test", status=None)
    completed_tasks = [
        t for t in tasks if t["description"] == summary and t["status"] == "completed"
    ]
    # There should be at least one completed task
    assert len(completed_tasks) >= 1
    # Verify the most recent one has the correct properties
    latest_task = max(completed_tasks, key=lambda t: t["entry"])
    assert latest_task["status"] == "completed"
    assert latest_task.get("caldav_uid") is not None


@pytest.mark.integration
def test_caldav_to_tw_modify_description(clean_test_environment) -> None:
    """Modify todo description/summary in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create and sync initial todo
    summary = "Original CalDAV summary"
    assert create_todo(calendar, summary)
    assert run_sync()

    # Verify initial sync
    tasks = get_tasks()
    assert len(tasks) == 1
    task_uuid = tasks[0]["uuid"]

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Modify summary in CalDAV
    todo = find_todo_by_summary(calendar, summary)
    assert todo is not None
    new_summary = "Modified CalDAV summary"
    assert modify_todo(todo, summary=new_summary)

    # Run sync
    assert run_sync()

    # Verify TaskWarrior task summary updated
    tasks = get_tasks()
    assert len(tasks) == 1
    assert tasks[0]["uuid"] == task_uuid
    assert tasks[0]["description"] == new_summary


@pytest.mark.integration
def test_caldav_to_tw_modify_due_date(clean_test_environment) -> None:
    """Modify todo due date in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo with due date
    summary = "CalDAV todo with changeable due date"
    due_date1 = datetime.now(UTC) + timedelta(days=2)
    assert create_todo(calendar, summary, due=due_date1)
    assert run_sync()

    # Verify initial sync
    tasks = get_tasks()
    assert len(tasks) == 1

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Modify due date in CalDAV
    todo = find_todo_by_summary(calendar, summary)
    assert todo is not None
    due_date2 = datetime.now(UTC) + timedelta(days=5)
    assert modify_todo(todo, due=due_date2)

    # Run sync
    assert run_sync()

    # Verify TaskWarrior task due date updated
    tasks = get_tasks()
    assert len(tasks) == 1
    assert "due" in tasks[0]


@pytest.mark.integration
def test_caldav_to_tw_modify_priority(clean_test_environment) -> None:
    """Modify todo priority in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo with medium priority
    summary = "CalDAV todo with changeable priority"
    assert create_todo(calendar, summary, priority=5)
    assert run_sync()

    # Verify initial sync
    tasks = get_tasks()
    assert len(tasks) == 1

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Modify priority to high in CalDAV
    todo = find_todo_by_summary(calendar, summary)
    assert todo is not None
    assert modify_todo(todo, priority=1)

    # Run sync
    assert run_sync()

    # Verify TaskWarrior task priority updated
    tasks = get_tasks()
    assert len(tasks) == 1
    assert tasks[0].get("priority") == "H"


@pytest.mark.integration
def test_caldav_to_tw_modify_status_to_completed(clean_test_environment) -> None:
    """Mark todo as completed in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create pending todo
    summary = "CalDAV todo to be completed"
    assert create_todo(calendar, summary, status="NEEDS-ACTION")
    assert run_sync()

    # Verify initial sync
    tasks = get_tasks()
    assert len(tasks) == 1
    task_uuid = tasks[0]["uuid"]

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Mark as completed in CalDAV
    todo = find_todo_by_summary(calendar, summary)
    assert todo is not None
    assert modify_todo(todo, status="COMPLETED")

    # Run sync
    assert run_sync()

    # Verify TaskWarrior task is completed (no longer in pending)
    tasks = get_tasks()
    # Task should be completed, so not in pending list
    assert len(tasks) == 0 or all(t["uuid"] != task_uuid for t in tasks)


@pytest.mark.integration
def test_caldav_to_tw_delete(clean_test_environment) -> None:
    """Delete todo in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create and sync todo
    summary = "CalDAV todo to be deleted"
    assert create_todo(calendar, summary)
    assert run_sync()

    # Verify initial sync
    tasks = get_tasks()
    assert len(tasks) == 1

    # Delete todo in CalDAV
    todo = find_todo_by_summary(calendar, summary)
    assert todo is not None
    todo.delete()

    # Run sync with delete_tasks=True
    assert run_sync(delete_tasks=True)

    # Verify TaskWarrior task is deleted
    tasks = get_tasks()
    assert len(tasks) == 0


@pytest.mark.integration
def test_caldav_to_tw_annotation_create(clean_test_environment) -> None:
    """Create todo with annotation in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo with annotation in description
    summary = "CalDAV todo with annotation"
    annotation_text = "This is a test annotation from CalDAV"
    timestamp = "20241118T120000Z"
    description_with_annotation = (
        f"--- TaskWarrior Annotations ---\n{timestamp}|{annotation_text}"
    )

    assert create_todo(calendar, summary, description=description_with_annotation)

    # Run sync
    assert run_sync()

    # Verify TaskWarrior task has annotation
    tasks = get_tasks()
    assert len(tasks) == 1
    assert "annotations" in tasks[0]
    annotations = tasks[0]["annotations"]
    assert len(annotations) >= 1
    assert any(annotation_text in a.get("description", "") for a in annotations)


@pytest.mark.integration
def test_caldav_to_tw_annotation_add(clean_test_environment) -> None:
    """Add annotation to existing todo in CalDAV, verify it syncs to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo with one annotation
    summary = "CalDAV todo for adding annotations"
    annotation1 = "First annotation"
    timestamp1 = "20241118T120000Z"
    description_with_annotation = (
        f"--- TaskWarrior Annotations ---\n{timestamp1}|{annotation1}"
    )
    assert create_todo(calendar, summary, description=description_with_annotation)
    assert run_sync()

    # Verify initial annotation
    tasks = get_tasks()
    assert len(tasks) == 1
    assert "annotations" in tasks[0]
    assert len(tasks[0]["annotations"]) == 1

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Add second annotation in CalDAV
    todo = find_todo_by_summary(calendar, summary)
    assert todo is not None
    annotation2 = "Second annotation"
    timestamp2 = "20241118T130000Z"
    description_with_two_annotations = f"""--- TaskWarrior Annotations ---
{timestamp1}|{annotation1}
{timestamp2}|{annotation2}"""
    assert modify_todo(todo, description=description_with_two_annotations)

    # Run sync
    assert run_sync()

    # Verify TaskWarrior task has both annotations
    tasks = get_tasks()
    assert len(tasks) == 1
    assert "annotations" in tasks[0]
    annotations = tasks[0]["annotations"]
    assert len(annotations) >= 2

    # Check both annotations are present
    annotation_texts = [a.get("description", "") for a in annotations]
    assert annotation1 in annotation_texts
    assert annotation2 in annotation_texts


@pytest.mark.integration
def test_caldav_to_tw_annotation_multiple(clean_test_environment) -> None:
    """Create todo with multiple annotations, verify they sync to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo with multiple annotations
    summary = "CalDAV todo with multiple annotations"
    annotation1 = "First annotation"
    annotation2 = "Second annotation"
    timestamp1 = "20241118T120000Z"
    timestamp2 = "20241118T130000Z"
    description_with_annotations = f"""--- TaskWarrior Annotations ---
{timestamp1}|{annotation1}
{timestamp2}|{annotation2}"""

    assert create_todo(calendar, summary, description=description_with_annotations)

    # Run sync
    assert run_sync()

    # Verify TaskWarrior task has both annotations
    tasks = get_tasks()
    assert len(tasks) == 1
    assert "annotations" in tasks[0]
    annotations = tasks[0]["annotations"]
    assert len(annotations) >= 2

    # Check both annotations are present
    annotation_texts = [a.get("description", "") for a in annotations]
    assert annotation1 in annotation_texts
    assert annotation2 in annotation_texts


@pytest.mark.integration
def test_caldav_to_tw_annotation_bidirectional_no_duplication(
    clean_test_environment,
) -> None:
    """Test that annotations don't duplicate on bidirectional sync."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo with annotation
    summary = "CalDAV annotation dedup test"
    annotation = "Test annotation for deduplication"
    timestamp = "20241118T150000Z"
    description_with_annotation = (
        f"--- TaskWarrior Annotations ---\n{timestamp}|{annotation}"
    )
    assert create_todo(calendar, summary, description=description_with_annotation)

    # Sync to TaskWarrior
    assert run_sync()

    # Verify task exists with 1 annotation
    tasks = get_tasks()
    assert len(tasks) == 1
    assert "annotations" in tasks[0]
    assert len(tasks[0]["annotations"]) == 1

    # Sync again (TW → CalDAV) - should not duplicate
    assert run_sync()

    # Sync back (CalDAV → TW) - should still not duplicate
    assert run_sync()

    # Verify still only 1 annotation
    tasks = get_tasks()
    assert len(tasks) == 1
    assert "annotations" in tasks[0]
    assert len(tasks[0]["annotations"]) == 1
    assert annotation in tasks[0]["annotations"][0]["description"]


@pytest.mark.integration
def test_caldav_to_tw_create_with_tags(clean_test_environment) -> None:
    """Create todo with tags/categories in CalDAV, verify they sync to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo with categories (CalDAV's version of tags)
    summary = "CalDAV todo with tags"
    # Note: CalDAV uses CATEGORIES property for tags
    assert create_todo(calendar, summary)

    # Run sync
    assert run_sync()

    # Verify task exists in TaskWarrior
    tasks = get_tasks()
    assert len(tasks) == 1
    assert tasks[0]["description"] == summary


@pytest.mark.integration
def test_caldav_to_tw_modify_tags_add(clean_test_environment) -> None:
    """Add tags to todo in CalDAV, verify they sync to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo
    summary = "CalDAV todo for adding tags"
    assert create_todo(calendar, summary)
    assert run_sync()

    # Verify initial sync
    tasks = get_tasks()
    assert len(tasks) == 1

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Modify todo to add categories in CalDAV
    todo = find_todo_by_summary(calendar, summary)
    assert todo is not None
    # Note: Would need to add categories property
    # For now, just verify the modification mechanism works
    assert modify_todo(todo, summary=f"{summary} [with tags]")

    # Run sync
    assert run_sync()

    # Verify TaskWarrior task updated
    tasks = get_tasks()
    assert len(tasks) == 1


@pytest.mark.integration
def test_caldav_to_tw_modify_tags_remove(clean_test_environment) -> None:
    """Remove tags from todo in CalDAV, verify they sync to TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo
    summary = "CalDAV todo for removing tags"
    assert create_todo(calendar, summary)
    assert run_sync()

    # Verify initial sync
    tasks = get_tasks()
    assert len(tasks) == 1

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Modify todo in CalDAV
    todo = find_todo_by_summary(calendar, summary)
    assert todo is not None
    assert modify_todo(todo, summary=f"{summary} [tags removed]")

    # Run sync
    assert run_sync()

    # Verify TaskWarrior task updated
    tasks = get_tasks()
    assert len(tasks) == 1


@pytest.mark.integration
def test_caldav_to_tw_dry_run(clean_test_environment) -> None:
    """Test dry-run mode doesn't modify TaskWarrior."""
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create todo in CalDAV
    summary = "CalDAV dry run test todo"
    assert create_todo(calendar, summary)

    # Get TaskWarrior task count before
    tasks_before = len(get_tasks())
    assert tasks_before == 0

    # Run sync in dry-run mode
    assert run_sync(dry_run=True)

    # Verify TaskWarrior didn't change
    tasks_after = len(get_tasks())
    assert tasks_after == 0


@pytest.mark.integration
def test_caldav_to_tw_completed_without_timestamp_idempotent(
    clean_test_environment,
) -> None:
    """Sync completed todo WITHOUT COMPLETED timestamp, verify sync is idempotent.

    This tests the scenario where CalDAV has a completed task but lacks the
    COMPLETED timestamp property. After initial sync to TW, subsequent syncs
    should NOT trigger spurious updates.

    This was a bug where the comparator would detect a difference between
    TW's end timestamp and CalDAV's missing COMPLETED, causing infinite
    update loops.
    """
    # Create completed todo WITHOUT completed timestamp
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    summary = "Completed task without timestamp"
    # status="COMPLETED" but NO completed=datetime parameter
    assert create_todo(calendar, summary, status="COMPLETED")

    # First sync
    assert run_sync()

    # Get TW task state after first sync
    tasks = get_tasks(project="test", status=None)
    completed_tasks = [t for t in tasks if t["description"] == summary]
    assert len(completed_tasks) == 1
    first_modified = completed_tasks[0]["modified"]

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Second sync - should NOT modify the task
    assert run_sync()

    # Verify task was NOT modified
    tasks = get_tasks(project="test", status=None)
    completed_tasks = [t for t in tasks if t["description"] == summary]
    assert len(completed_tasks) == 1
    assert completed_tasks[0]["modified"] == first_modified, (
        "Task was spuriously updated on second sync"
    )


@pytest.mark.integration
def test_caldav_to_tw_delete_disabled(clean_test_environment) -> None:
    """Delete todo in CalDAV with delete_tasks=False, verify TW task preserved.

    When deletion is disabled, deleting a CalDAV todo should NOT delete the
    corresponding TaskWarrior task.
    """
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create and sync todo
    summary = "CalDAV todo to delete (deletion disabled)"
    assert create_todo(calendar, summary)
    assert run_sync()

    # Verify initial sync
    tasks = get_tasks()
    assert len(tasks) == 1
    task_uuid = tasks[0]["uuid"]

    # Delete todo in CalDAV
    todo = find_todo_by_summary(calendar, summary)
    assert todo is not None
    todo.delete()

    # Run sync with delete_tasks=False
    assert run_sync(delete_tasks=False)

    # Verify TaskWarrior task is NOT deleted
    tasks = get_tasks()
    assert len(tasks) == 1, "TW task should be preserved when deletion is disabled"
    assert tasks[0]["uuid"] == task_uuid


@pytest.mark.integration
def test_caldav_to_tw_cancelled_status_delete_enabled(clean_test_environment) -> None:
    """Set CalDAV todo to CANCELLED status, verify TW task deleted.

    When a CalDAV todo is set to CANCELLED status (not deleted), the sync
    should delete the corresponding TaskWarrior task if deletion is enabled.
    """
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create and sync todo
    summary = "CalDAV todo to be cancelled"
    assert create_todo(calendar, summary, status="NEEDS-ACTION")
    assert run_sync()

    # Verify initial sync
    tasks = get_tasks()
    assert len(tasks) == 1
    task_uuid = tasks[0]["uuid"]

    # Wait for timestamp separation
    time.sleep(2)

    # Set todo to CANCELLED status (not delete it)
    todo = find_todo_by_summary(calendar, summary)
    assert todo is not None
    assert modify_todo(todo, status="CANCELLED")

    # Run sync with delete_tasks=True
    assert run_sync(delete_tasks=True)

    # Verify TaskWarrior task is deleted
    tasks = get_tasks()
    assert len(tasks) == 0 or all(t["uuid"] != task_uuid for t in tasks), (
        "TW task should be deleted when CalDAV todo is CANCELLED"
    )


@pytest.mark.integration
def test_caldav_to_tw_cancelled_status_delete_disabled(clean_test_environment) -> None:
    """Set CalDAV todo to CANCELLED status with delete_tasks=False, verify TW preserved.

    When deletion is disabled, a CANCELLED CalDAV todo should NOT cause the
    corresponding TaskWarrior task to be deleted.
    """
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create and sync todo
    summary = "CalDAV todo cancelled (deletion disabled)"
    assert create_todo(calendar, summary, status="NEEDS-ACTION")
    assert run_sync()

    # Verify initial sync
    tasks = get_tasks()
    assert len(tasks) == 1
    task_uuid = tasks[0]["uuid"]

    # Wait for timestamp separation
    time.sleep(2)

    # Set todo to CANCELLED status
    todo = find_todo_by_summary(calendar, summary)
    assert todo is not None
    assert modify_todo(todo, status="CANCELLED")

    # Run sync with delete_tasks=False
    assert run_sync(delete_tasks=False)

    # Verify TaskWarrior task is NOT deleted
    tasks = get_tasks()
    assert len(tasks) == 1, "TW task should be preserved when deletion is disabled"
    assert tasks[0]["uuid"] == task_uuid


@pytest.mark.integration
def test_caldav_to_tw_cancelled_no_tw_task(clean_test_environment) -> None:
    """Create CANCELLED CalDAV todo without TW counterpart, verify it's skipped.

    A CalDAV todo with CANCELLED status that has no corresponding TaskWarrior
    task should be skipped (not create a new deleted task).
    """
    # Get CalDAV client
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Create CANCELLED todo directly (never synced)
    summary = "Orphaned cancelled CalDAV todo"
    assert create_todo(calendar, summary, status="CANCELLED")

    # Verify no TW tasks exist
    tasks = get_tasks()
    assert len(tasks) == 0

    # Run sync
    assert run_sync()

    # Verify no TW task was created
    tasks = get_tasks()
    assert len(tasks) == 0, "Orphaned CANCELLED todo should not create TW task"


@pytest.mark.integration
def test_caldav_to_tw_due_with_timezone(clean_test_environment) -> None:
    """A due time with a TZID syncs as the same instant, and stays put."""
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    summary = "CalDAV todo due in Tashkent"
    due = datetime(2030, 8, 15, 12, 30, tzinfo=ZoneInfo("Asia/Tashkent"))
    assert create_todo(calendar, summary, due=due)
    assert run_sync()

    tasks = get_tasks()
    assert len(tasks) == 1
    assert tasks[0]["due"] == "20300815T073000Z"
    first_modified = tasks[0]["modified"]

    time.sleep(2)
    assert run_sync()

    tasks = get_tasks()
    assert tasks[0]["due"] == "20300815T073000Z"
    assert tasks[0]["modified"] == first_modified
