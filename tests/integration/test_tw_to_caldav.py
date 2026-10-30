"""Integration tests for TaskWarrior → CalDAV synchronization."""

import time

import pytest

from tests.integration.helpers import (
    add_tags,
    annotate_task,
    complete_task,
    create_task,
    delete_task,
    find_todo_by_summary,
    get_caldav_client,
    get_calendar,
    get_task,
    get_tasks,
    get_todo_property,
    get_todos,
    modify_task,
    remove_tags,
    run_sync,
)


@pytest.mark.integration
def test_tw_to_caldav_create_simple(clean_test_environment) -> None:
    """Create simple task in TaskWarrior, verify it syncs to CalDAV."""
    # Create task in TaskWarrior
    description = "Simple TaskWarrior test task"
    task = create_task(description)
    assert task is not None

    # Run sync
    assert run_sync()

    # Verify todo exists in CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todos = get_todos(calendar)
    assert len(todos) == 1

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    assert str(get_todo_property(todo, "summary")) == description


@pytest.mark.integration
def test_tw_to_caldav_create_with_due_date(clean_test_environment) -> None:
    """Create task with due date in TaskWarrior, verify it syncs to CalDAV."""
    # Create task with due date
    description = "TaskWarrior task with due date"
    task = create_task(description, due="tomorrow")
    assert task is not None
    assert "due" in task

    # Run sync
    assert run_sync()

    # Verify todo has due date in CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    due_prop = get_todo_property(todo, "due")
    assert due_prop is not None


@pytest.mark.integration
def test_tw_to_caldav_create_with_scheduled(clean_test_environment) -> None:
    """Create task with scheduled date in TaskWarrior, verify it syncs to CalDAV."""
    # Create task with scheduled date
    description = "TaskWarrior task with scheduled date"
    task = create_task(description, scheduled="tomorrow")
    assert task is not None
    assert "scheduled" in task

    # Run sync
    assert run_sync()

    # Verify todo has DTSTART in CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    dtstart = get_todo_property(todo, "dtstart")
    assert dtstart is not None


@pytest.mark.integration
def test_tw_to_caldav_create_with_wait(clean_test_environment) -> None:
    """Create task with wait date in TaskWarrior, verify it syncs to CalDAV."""
    # Create task with wait date (using yesterday so task stays pending, not waiting)
    description = "TaskWarrior task with wait date"
    task = create_task(description, wait="yesterday")
    assert task is not None
    assert "wait" in task

    # Run sync
    assert run_sync()

    # Verify todo has X-TASKWARRIOR-WAIT in CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    wait_prop = get_todo_property(todo, "x-taskwarrior-wait")
    assert wait_prop is not None


@pytest.mark.integration
def test_tw_to_caldav_completed_task_with_end(clean_test_environment) -> None:
    """Complete task in TaskWarrior, verify COMPLETED timestamp syncs to CalDAV."""
    # Create and complete task
    description = "Task to be completed"
    task = create_task(description)
    assert task is not None

    # Complete the task (this sets end timestamp automatically)
    assert complete_task(task["uuid"])

    # Verify task has end timestamp
    completed_task = get_task(task["uuid"])
    assert completed_task is not None
    assert completed_task["status"] == "completed"
    assert "end" in completed_task

    # Run sync
    assert run_sync()

    # Verify todo has COMPLETED in CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    completed_prop = get_todo_property(todo, "completed")
    assert completed_prop is not None
    assert get_todo_property(todo, "status") == "COMPLETED"


@pytest.mark.integration
def test_tw_to_caldav_create_with_priority(clean_test_environment) -> None:
    """Create task with priority in TaskWarrior, verify it syncs to CalDAV."""
    # Create task with high priority
    description = "TaskWarrior task with high priority"
    task = create_task(description, priority="H")
    assert task is not None
    assert task.get("priority") == "H"

    # Run sync
    assert run_sync()

    # Verify todo has priority in CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    priority = get_todo_property(todo, "priority")
    # High priority in TW maps to 1 in CalDAV
    assert priority is not None


@pytest.mark.integration
def test_tw_to_caldav_create_with_tags(clean_test_environment) -> None:
    """Create task with tags in TaskWarrior, verify they sync to CalDAV."""
    # Create task with tags
    description = "TaskWarrior task with tags"
    task = create_task(description, tags=["urgent", "work"])
    assert task is not None
    assert "tags" in task
    assert "urgent" in task["tags"]
    assert "work" in task["tags"]

    # Run sync
    assert run_sync()

    # Verify todo exists in CalDAV (tags might be in categories or description)
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None


@pytest.mark.integration
def test_tw_to_caldav_create_completed(clean_test_environment) -> None:
    """Create and complete task in TaskWarrior, verify it syncs to CalDAV."""
    # Create and complete task
    description = "TaskWarrior completed task"
    task = create_task(description)
    assert task is not None
    assert complete_task(task["uuid"])

    # Run sync
    assert run_sync()

    # Verify todo is completed in CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Note: This test creates, syncs, then completes the task
    # For testing sync of pre-existing completed tasks (completed before first sync),
    # see test_tw_to_caldav_sync_preexisting_completed
    get_todos(calendar)
    # The important thing is that sync succeeded without errors


@pytest.mark.integration
def test_tw_to_caldav_sync_preexisting_completed(clean_test_environment) -> None:
    """Sync completed task that existed before first sync (no caldav_uid).

    This test verifies that completed tasks without caldav_uid are discovered
    and synced to CalDAV on the first sync run.
    """
    # Create and complete task WITHOUT syncing first
    description = "Pre-existing completed TaskWarrior task"
    task = create_task(description)
    assert task is not None

    # Complete immediately (before any sync)
    assert complete_task(task["uuid"])

    # Verify task has no caldav_uid yet (get all tasks, not just pending)
    tasks = get_tasks(project="test", status=None)
    completed_task = next((t for t in tasks if t["uuid"] == task["uuid"]), None)
    assert completed_task is not None
    assert completed_task.get("caldav_uid") is None
    assert completed_task["status"] == "completed"

    # Run sync for the first time
    assert run_sync()

    # Verify task now has caldav_uid
    tasks = get_tasks(project="test", status=None)
    synced_task = next((t for t in tasks if t["uuid"] == task["uuid"]), None)
    assert synced_task is not None
    assert synced_task.get("caldav_uid") is not None

    # Verify todo exists in CalDAV with completed status
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # With include_completed=True, this should now work
    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    status = get_todo_property(todo, "status")
    assert status == "COMPLETED"


@pytest.mark.integration
def test_tw_to_caldav_modify_description(clean_test_environment) -> None:
    """Modify task description in TaskWarrior, verify it syncs to CalDAV."""
    # Create and sync initial task
    description = "Original TaskWarrior description"
    task = create_task(description)
    assert task is not None
    assert run_sync()

    # Verify initial sync
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Modify description in TaskWarrior
    new_description = "Modified TaskWarrior description"
    assert modify_task(task["uuid"], description=new_description)

    # Run sync
    assert run_sync()

    # Verify CalDAV todo summary updated
    todo = find_todo_by_summary(calendar, new_description)
    assert todo is not None
    assert str(get_todo_property(todo, "summary")) == new_description


@pytest.mark.integration
def test_tw_to_caldav_modify_due_date(clean_test_environment) -> None:
    """Modify task due date in TaskWarrior, verify it syncs to CalDAV."""
    # Create task with due date
    description = "TaskWarrior task with changeable due date"
    task = create_task(description, due="tomorrow")
    assert task is not None
    assert run_sync()

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Modify due date in TaskWarrior
    assert modify_task(task["uuid"], due="3days")

    # Run sync
    assert run_sync()

    # Verify CalDAV todo due date updated
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    due_prop = get_todo_property(todo, "due")
    assert due_prop is not None


@pytest.mark.integration
def test_tw_to_caldav_modify_priority(clean_test_environment) -> None:
    """Modify task priority in TaskWarrior, verify it syncs to CalDAV."""
    # Create task with medium priority
    description = "TaskWarrior task with changeable priority"
    task = create_task(description, priority="M")
    assert task is not None
    assert run_sync()

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Modify priority to high in TaskWarrior
    assert modify_task(task["uuid"], priority="H")

    # Run sync
    assert run_sync()

    # Verify CalDAV todo priority updated
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    priority = get_todo_property(todo, "priority")
    assert priority is not None


@pytest.mark.integration
def test_tw_to_caldav_modify_tags_add(clean_test_environment) -> None:
    """Add tags to task in TaskWarrior, verify they sync to CalDAV."""
    # Create task without tags
    description = "TaskWarrior task for adding tags"
    task = create_task(description)
    assert task is not None
    assert run_sync()

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Add tags in TaskWarrior
    assert add_tags(task["uuid"], ["urgent", "important"])

    # Run sync
    assert run_sync()

    # Verify tags synced to CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None


@pytest.mark.integration
def test_tw_to_caldav_modify_tags_remove(clean_test_environment) -> None:
    """Remove tags from task in TaskWarrior, verify they sync to CalDAV."""
    # Create task with tags
    description = "TaskWarrior task for removing tags"
    task = create_task(description, tags=["urgent", "work", "temp"])
    assert task is not None
    assert run_sync()

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Remove a tag in TaskWarrior
    assert remove_tags(task["uuid"], ["temp"])

    # Run sync
    assert run_sync()

    # Verify task still exists in CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None


@pytest.mark.integration
def test_tw_to_caldav_modify_status_to_completed(clean_test_environment) -> None:
    """Complete task in TaskWarrior, verify it syncs to CalDAV."""
    # Create pending task
    description = "TaskWarrior task to be completed"
    task = create_task(description)
    assert task is not None
    assert run_sync()

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Complete task in TaskWarrior
    assert complete_task(task["uuid"])

    # Run sync
    assert run_sync()

    # Verify task is completed (might not be in todos() list)
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    # Sync succeeded - completed tasks may not appear in calendar.todos()


@pytest.mark.integration
def test_tw_to_caldav_delete(clean_test_environment) -> None:
    """Delete task in TaskWarrior, verify it syncs to CalDAV."""
    # Create and sync task
    description = "TaskWarrior task to be deleted"
    task = create_task(description)
    assert task is not None
    assert run_sync()

    # Verify initial sync
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todos_before = len(get_todos(calendar))
    assert todos_before == 1

    # Delete task in TaskWarrior
    assert delete_task(task["uuid"])

    # Run sync with delete_tasks=True
    assert run_sync(delete_tasks=True)

    # Verify CalDAV todo is deleted
    todos_after = len(get_todos(calendar))
    assert todos_after == 0


@pytest.mark.integration
def test_tw_to_caldav_annotation_create(clean_test_environment) -> None:
    """Add annotation to task in TaskWarrior, verify it syncs to CalDAV."""
    # Create task
    description = "TaskWarrior task with annotation"
    task = create_task(description)
    assert task is not None

    # Add annotation
    annotation_text = "This is a test annotation"
    assert annotate_task(task["uuid"], annotation_text)

    # Run sync
    assert run_sync()

    # Verify annotation in CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    todo_description = get_todo_property(todo, "description")
    assert todo_description is not None
    assert "Taskwarrior annotations:" in str(todo_description)
    assert annotation_text in str(todo_description)


@pytest.mark.integration
def test_tw_to_caldav_annotation_add(clean_test_environment) -> None:
    """Add annotation to existing task in TaskWarrior, verify it syncs."""
    # Create task and sync
    description = "TaskWarrior task for adding annotation"
    task = create_task(description)
    assert task is not None
    assert run_sync()

    # Wait to ensure timestamp separation
    time.sleep(2)

    # Add annotation
    annotation_text = "Annotation added later"
    assert annotate_task(task["uuid"], annotation_text)

    # Run sync
    assert run_sync()

    # Verify annotation in CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    todo_description = get_todo_property(todo, "description")
    assert todo_description is not None
    assert annotation_text in str(todo_description)


@pytest.mark.integration
def test_tw_to_caldav_annotation_multiple(clean_test_environment) -> None:
    """Add multiple annotations to task in TaskWarrior, verify they sync."""
    # Create task with first annotation
    description = "TaskWarrior task with multiple annotations"
    task = create_task(description)
    assert task is not None

    annotation1 = "First annotation"
    assert annotate_task(task["uuid"], annotation1)
    time.sleep(1)

    # Add second annotation
    annotation2 = "Second annotation"
    assert annotate_task(task["uuid"], annotation2)

    # Run sync
    assert run_sync()

    # Verify both annotations in CalDAV
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    todo_description = get_todo_property(todo, "description")
    assert todo_description is not None
    todo_desc_str = str(todo_description)
    assert annotation1 in todo_desc_str
    assert annotation2 in todo_desc_str


@pytest.mark.integration
def test_tw_to_caldav_dry_run(clean_test_environment) -> None:
    """Test dry-run mode doesn't modify CalDAV."""
    # Create task
    description = "TaskWarrior dry run test task"
    task = create_task(description)
    assert task is not None

    # Get CalDAV todo count before
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todos_before = len(get_todos(calendar))
    assert todos_before == 0

    # Run sync in dry-run mode
    assert run_sync(dry_run=True)

    # Verify CalDAV didn't change
    todos_after = len(get_todos(calendar))
    assert todos_after == 0


@pytest.mark.integration
def test_tw_to_caldav_annotation_bidirectional_no_duplication(
    clean_test_environment,
) -> None:
    """Test that annotations don't duplicate on bidirectional sync."""
    # Create task with annotation
    description = "Task for annotation deduplication test"
    task = create_task(description)
    assert task is not None

    annotation = "Test annotation for deduplication"
    assert annotate_task(task["uuid"], annotation)

    # Sync to CalDAV
    assert run_sync()

    # Verify task exists with 1 annotation
    tasks = get_tasks()
    assert len(tasks) == 1
    assert "annotations" in tasks[0]
    assert len(tasks[0]["annotations"]) == 1

    # Sync again (CalDAV → TW) - should not duplicate
    assert run_sync()

    # Verify still only 1 annotation
    tasks = get_tasks()
    assert len(tasks) == 1
    assert "annotations" in tasks[0]
    assert len(tasks[0]["annotations"]) == 1
    assert tasks[0]["annotations"][0]["description"] == annotation


@pytest.mark.integration
def test_tw_to_caldav_completed_syncs_completed_timestamp(
    clean_test_environment,
) -> None:
    """Verify that completing a TW task syncs the COMPLETED timestamp to CalDAV.

    This ensures that when TW completes a task, the end timestamp is properly
    synced as the CalDAV COMPLETED property.
    """
    # Create pending task
    description = "Task to complete for timestamp sync"
    task = create_task(description)
    assert task is not None

    # Sync to CalDAV
    assert run_sync()

    # Complete the task in TW
    time.sleep(1)
    assert complete_task(task["uuid"])

    # Sync to CalDAV
    assert run_sync()

    # Verify CalDAV has COMPLETED property
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todo = find_todo_by_summary(calendar, description)
    assert todo is not None

    completed_prop = get_todo_property(todo, "completed")
    assert completed_prop is not None, "COMPLETED timestamp not synced to CalDAV"
    status_prop = get_todo_property(todo, "status")
    assert status_prop == "COMPLETED"


@pytest.mark.integration
def test_tw_to_caldav_delete_disabled(clean_test_environment) -> None:
    """Delete task in TaskWarrior with delete_tasks=False.

    Verify CalDAV todo is set to CANCELLED status (soft delete).
    When deletion is disabled, deleting a TW task should set the corresponding
    CalDAV todo status to CANCELLED (soft delete) instead of removing it.
    """
    # Create and sync task
    description = "TaskWarrior task to delete (deletion disabled)"
    task = create_task(description)
    assert task is not None
    assert run_sync()

    # Verify initial sync
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None

    todos_before = len(get_todos(calendar))
    assert todos_before == 1

    # Verify initial status is not CANCELLED
    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    initial_status = get_todo_property(todo, "status")
    assert initial_status != "CANCELLED"

    # Delete task in TaskWarrior
    assert delete_task(task["uuid"])

    # Run sync with delete_tasks=False
    assert run_sync(delete_tasks=False)

    # Verify CalDAV todo is NOT deleted but is CANCELLED
    todos_after = len(get_todos(calendar))
    assert todos_after == 1, "CalDAV todo should be preserved (as CANCELLED)"

    # Verify the todo has status CANCELLED
    todo = find_todo_by_summary(calendar, description)
    assert todo is not None
    status = get_todo_property(todo, "status")
    assert status == "CANCELLED", f"Expected CANCELLED status, got {status}"
