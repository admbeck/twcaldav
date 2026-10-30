"""Integration tests for the three-way merge against the last synced base."""

import time
from datetime import UTC, datetime, timedelta

import pytest

from tests.integration.helpers import (
    create_task,
    create_todo,
    find_todo_by_summary,
    get_caldav_client,
    get_calendar,
    get_task,
    get_tasks,
    get_todo_property,
    modify_task,
    modify_todo,
    run_sync,
    run_task_command,
)


def _calendar():
    _, principal = get_caldav_client()
    assert principal is not None
    calendar = get_calendar(principal)
    assert calendar is not None
    return calendar


def _due_date(task: dict) -> str:
    """Return the date part of a TaskWarrior due timestamp."""
    return task["due"][:8]


@pytest.mark.integration
def test_denotating_note_deletes_caldav_note(clean_test_environment) -> None:
    """Removing the note annotation in TaskWarrior removes the CalDAV note."""
    calendar = _calendar()
    summary = "Todo with a note to delete"
    assert create_todo(calendar, summary, description="Gate code 1234")
    assert run_sync()

    tasks = get_tasks()
    assert len(tasks) == 1
    assert [a["description"] for a in tasks[0]["annotations"]] == ["Gate code 1234"]

    time.sleep(2)
    _stdout, _stderr, code = run_task_command(
        [tasks[0]["uuid"], "denotate", "Gate code 1234"]
    )
    assert code == 0

    assert run_sync()
    todo = find_todo_by_summary(calendar, summary)
    assert "Gate code" not in str(get_todo_property(todo, "description") or "")

    # The note doesn't come back on the next sync
    assert run_sync()
    task = get_task(tasks[0]["uuid"])
    assert task is not None
    assert not task.get("annotations")
    todo = find_todo_by_summary(calendar, summary)
    assert "Gate code" not in str(get_todo_property(todo, "description") or "")


@pytest.mark.integration
def test_edits_to_different_fields_on_both_sides_survive(
    clean_test_environment,
) -> None:
    """A CalDAV due date change survives a later TaskWarrior priority change."""
    calendar = _calendar()
    task = create_task("Task edited on both sides", due="tomorrow", priority="L")
    assert task is not None
    assert run_sync()

    time.sleep(2)
    new_due = (datetime.now(UTC) + timedelta(days=10)).replace(microsecond=0)
    todo = find_todo_by_summary(calendar, "Task edited on both sides")
    assert modify_todo(todo, due=new_due)

    # TaskWarrior is modified last, so last write wins would drop the due date
    time.sleep(2)
    assert modify_task(task["uuid"], priority="H")

    assert run_sync()

    task = get_task(task["uuid"])
    assert task is not None
    assert task["priority"] == "H"
    assert _due_date(task) == new_due.strftime("%Y%m%d")

    todo = find_todo_by_summary(calendar, "Task edited on both sides")
    assert int(get_todo_property(todo, "priority")) == 1
    assert get_todo_property(todo, "due").dt.date() == new_due.date()


@pytest.mark.integration
def test_multi_client_edits_to_different_fields_survive(
    clean_test_environment, multi_client_setup
) -> None:
    """Two clients changing different fields both keep both changes."""
    client1, client2 = multi_client_setup
    task1 = create_task("Shared task", taskdata=client1, due="tomorrow", priority="L")
    assert task1 is not None
    assert run_sync(taskdata=client1)
    assert run_sync(taskdata=client2)
    task2 = get_tasks(taskdata=client2)[0]

    time.sleep(2)
    assert modify_task(task2["uuid"], taskdata=client2, due="10days")
    assert run_sync(taskdata=client2)

    time.sleep(2)
    assert modify_task(task1["uuid"], taskdata=client1, priority="H")
    assert run_sync(taskdata=client1)
    assert run_sync(taskdata=client2)

    task1 = get_task(task1["uuid"], taskdata=client1)
    task2 = get_task(task2["uuid"], taskdata=client2)
    assert task1 is not None and task2 is not None
    assert task1["priority"] == task2["priority"] == "H"
    assert _due_date(task1) == _due_date(task2)
    assert _due_date(task1) > (datetime.now(UTC) + timedelta(days=5)).strftime("%Y%m%d")
