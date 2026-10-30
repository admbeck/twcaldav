"""Helper functions for integration tests."""

import contextlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import caldav
from icalendar import Calendar, Todo

# Environment configuration
CALDAV_URL = os.getenv("CALDAV_URL", "http://localhost:5232/test-user/")
CALDAV_USERNAME = os.getenv("CALDAV_USERNAME", "test-user")
CALDAV_PASSWORD = os.getenv("CALDAV_PASSWORD", "test-pass")
CALDAV_CALENDAR_ID = os.getenv("CALDAV_CALENDAR_ID", "test-calendar")
TW_PROJECT = os.getenv("TW_PROJECT", "test")
TASKDATA = os.getenv("TASKDATA", None)
# Local timezone for TaskWarrior and twcaldav, so dates without a time are
# tested away from UTC
TIMEZONE = "Europe/Berlin"


# TaskWarrior operations


def run_task_command(
    args: list[str], taskdata: str | None = None
) -> tuple[str, str, int]:
    """Run a TaskWarrior command and return output.

    Args:
        args: Command arguments to pass to task.
        taskdata: Optional TASKDATA path to use instead of default.

    Returns:
        Tuple of (stdout, stderr, returncode).
    """
    cmd = ["task"]
    env = os.environ.copy()
    env["TZ"] = TIMEZONE
    taskdata_path = taskdata or TASKDATA

    if taskdata_path:
        env["TASKDATA"] = taskdata_path
        cmd.append(f"rc.data.location={taskdata_path}")

    cmd.extend(args)

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return result.stdout, result.stderr, result.returncode


def get_tasks(
    taskdata: str | None = None,
    project: str | None = None,
    status: str | None = "pending",
) -> list[dict]:
    """Get tasks from TaskWarrior.

    Args:
        taskdata: Optional TASKDATA path to use.
        project: Optional project filter (defaults to TW_PROJECT).
        status: Optional status filter (defaults to "pending").
                Use None to get all tasks regardless of status.

    Returns:
        List of task dictionaries.
    """
    proj = project or TW_PROJECT
    args = [f"project:{proj}"]

    # Add status filter if specified
    if status is not None:
        args.append(f"status:{status}")

    args.append("export")

    stdout, _, _ = run_task_command(args, taskdata=taskdata)
    if not stdout.strip():
        return []
    return json.loads(stdout)


def get_task(uuid: str, taskdata: str | None = None) -> dict | None:
    """Get a single task by UUID (any status).

    Args:
        uuid: Task UUID.
        taskdata: Optional TASKDATA path to use.

    Returns:
        Task dictionary or None if not found.
    """
    args = [f"{uuid}", "export"]
    stdout, _, code = run_task_command(args, taskdata=taskdata)
    if code != 0 or not stdout.strip():
        return None

    tasks = json.loads(stdout)
    return tasks[0] if tasks else None


def create_task(description: str, taskdata: str | None = None, **kwargs) -> dict | None:
    """Create a task in TaskWarrior.

    Args:
        description: Task description.
        taskdata: Optional TASKDATA path to use.
        **kwargs: Additional task attributes (due, priority, tags, etc.).

    Returns:
        The created task dictionary or None.
    """
    args = ["add", description, f"project:{TW_PROJECT}"]

    if "due" in kwargs:
        args.append(f"due:{kwargs['due']}")
    if "scheduled" in kwargs:
        args.append(f"scheduled:{kwargs['scheduled']}")
    if "wait" in kwargs:
        args.append(f"wait:{kwargs['wait']}")
    if "priority" in kwargs:
        args.append(f"priority:{kwargs['priority']}")
    if "tags" in kwargs:
        tags = kwargs["tags"]
        if isinstance(tags, list):
            for tag in tags:
                args.append(f"+{tag}")
        else:
            args.append(f"+{tags}")

    _stdout, _stderr, code = run_task_command(args, taskdata=taskdata)

    if code != 0:
        return None

    # Get the most recently created task
    tasks = get_tasks(taskdata=taskdata)
    if tasks:
        return max(tasks, key=lambda t: t.get("entry", ""))
    return None


def modify_task(uuid: str, taskdata: str | None = None, **modifications) -> bool:
    """Modify a TaskWarrior task.

    Args:
        uuid: Task UUID.
        taskdata: Optional TASKDATA path to use.
        **modifications: Modifications to apply.

    Returns:
        True if successful, False otherwise.
    """
    args = ["rc.confirmation=off", uuid, "modify"]

    for key, value in modifications.items():
        if key == "description":
            args.append(value)
        else:
            args.append(f"{key}:{value}")

    _stdout, _stderr, code = run_task_command(args, taskdata=taskdata)
    return code == 0


def complete_task(uuid: str, taskdata: str | None = None) -> bool:
    """Mark a TaskWarrior task as done.

    Args:
        uuid: Task UUID.
        taskdata: Optional TASKDATA path to use.

    Returns:
        True if successful, False otherwise.
    """
    _stdout, _stderr, code = run_task_command(
        ["rc.confirmation=off", uuid, "done"], taskdata=taskdata
    )
    return code == 0


def delete_task(uuid: str, taskdata: str | None = None) -> bool:
    """Delete a TaskWarrior task.

    Args:
        uuid: Task UUID.
        taskdata: Optional TASKDATA path to use.

    Returns:
        True if successful, False otherwise.
    """
    _stdout, _stderr, code = run_task_command(
        ["rc.confirmation=off", uuid, "delete"], taskdata=taskdata
    )
    return code == 0


def annotate_task(uuid: str, annotation: str, taskdata: str | None = None) -> bool:
    """Add an annotation to a TaskWarrior task.

    Args:
        uuid: Task UUID.
        annotation: Annotation text to add.
        taskdata: Optional TASKDATA path to use.

    Returns:
        True if successful, False otherwise.
    """
    _stdout, _stderr, code = run_task_command(
        [uuid, "annotate", annotation], taskdata=taskdata
    )
    return code == 0


def add_tags(uuid: str, tags: list[str], taskdata: str | None = None) -> bool:
    """Add tags to a TaskWarrior task.

    Args:
        uuid: Task UUID.
        tags: List of tags to add.
        taskdata: Optional TASKDATA path to use.

    Returns:
        True if successful, False otherwise.
    """
    args = ["rc.confirmation=off", uuid, "modify"]
    for tag in tags:
        args.append(f"+{tag}")

    _stdout, _stderr, code = run_task_command(args, taskdata=taskdata)
    return code == 0


def remove_tags(uuid: str, tags: list[str], taskdata: str | None = None) -> bool:
    """Remove tags from a TaskWarrior task.

    Args:
        uuid: Task UUID.
        tags: List of tags to remove.
        taskdata: Optional TASKDATA path to use.

    Returns:
        True if successful, False otherwise.
    """
    args = ["rc.confirmation=off", uuid, "modify"]
    for tag in tags:
        args.append(f"-{tag}")

    _stdout, _stderr, code = run_task_command(args, taskdata=taskdata)
    return code == 0


# CalDAV operations


def get_caldav_client() -> tuple[caldav.DAVClient | None, caldav.Principal | None]:
    """Create CalDAV client connection.

    Returns:
        Tuple of (client, principal) or (None, None) on failure.
    """
    try:
        client = caldav.DAVClient(
            url=CALDAV_URL, username=CALDAV_USERNAME, password=CALDAV_PASSWORD
        )
        principal = client.principal()
        return client, principal
    except Exception:
        return None, None


def get_calendar(
    principal: caldav.Principal, calendar_id: str | None = None
) -> caldav.Calendar | None:
    """Get the test calendar.

    Args:
        principal: CalDAV principal.
        calendar_id: Calendar ID to search for (defaults to CALDAV_CALENDAR_ID).

    Returns:
        Calendar object or None.
    """
    try:
        cal_id = calendar_id or CALDAV_CALENDAR_ID
        calendars = principal.calendars()
        for cal in calendars:
            if cal.id == cal_id or cal_id in str(cal.url):
                return cal
        return None
    except Exception:
        return None


def get_todos(calendar: caldav.Calendar) -> list:
    """Get all todos from CalDAV calendar, including completed ones.

    Args:
        calendar: Calendar object.

    Returns:
        List of todo objects (including completed).
    """
    try:
        return calendar.todos(include_completed=True)
    except Exception:
        return []


def create_todo(calendar: caldav.Calendar, summary: str, **kwargs) -> bool:
    """Create a todo in CalDAV calendar.

    Args:
        calendar: Calendar object.
        summary: Todo summary.
        **kwargs: Additional todo attributes (due, priority, description, status, etc.).

    Returns:
        True if successful, False otherwise.
    """
    try:
        cal = Calendar()
        todo = Todo()

        todo.add("summary", summary)
        todo.add("status", kwargs.get("status", "NEEDS-ACTION"))
        todo.add("uid", f"test-{datetime.now().timestamp()}")

        if "due" in kwargs:
            todo.add("due", kwargs["due"])
        if "dtstart" in kwargs:
            todo.add("dtstart", kwargs["dtstart"])
        if "wait" in kwargs:
            todo.add("X-TASKWARRIOR-WAIT", kwargs["wait"])
        if "completed" in kwargs:
            todo.add("completed", kwargs["completed"])
        if "priority" in kwargs:
            todo.add("priority", kwargs["priority"])
        if "description" in kwargs:
            todo.add("description", kwargs["description"])

        cal.add_component(todo)

        calendar.save_todo(cal.to_ical())
        return True
    except Exception:
        return False


def modify_todo(todo, **modifications) -> bool:
    """Modify a CalDAV todo.

    Args:
        todo: Todo object.
        **modifications: Modifications to apply (summary, priority, status, etc.).

    Returns:
        True if successful, False otherwise.
    """
    try:
        ical = Calendar.from_ical(todo.data)

        for component in ical.walk():
            if component.name == "VTODO":
                # Apply modifications
                for key, value in modifications.items():
                    if key in component:
                        del component[key]
                    component.add(key, value)

                # Update LAST-MODIFIED
                if "last-modified" in component:
                    del component["last-modified"]
                component.add("last-modified", datetime.now(UTC))
                break

        # Save modified todo
        todo.data = ical.to_ical()
        todo.save()
        return True
    except Exception:
        return False


def delete_todo(todo) -> bool:
    """Delete a CalDAV todo.

    Args:
        todo: Todo object.

    Returns:
        True if successful, False otherwise.
    """
    try:
        todo.delete()
        return True
    except Exception:
        return False


def find_todo_by_summary(calendar: caldav.Calendar, summary: str):
    """Find a todo by its summary.

    Args:
        calendar: Calendar object.
        summary: Summary to search for.

    Returns:
        Todo object or None.
    """
    todos = get_todos(calendar)
    for todo in todos:
        try:
            ical = Calendar.from_ical(todo.data)
            for component in ical.walk():
                if component.name == "VTODO":
                    todo_summary = str(component.get("summary", ""))
                    if summary in todo_summary:
                        return todo
        except Exception:
            continue
    return None


def get_todo_property(todo, property_name: str):
    """Get a property from a CalDAV todo.

    Args:
        todo: Todo object.
        property_name: Property name to retrieve.

    Returns:
        Property value or None.
    """
    try:
        ical = Calendar.from_ical(todo.data)
        for component in ical.walk():
            if component.name == "VTODO":
                return component.get(property_name)
    except Exception:
        pass
    return None


# Sync operations


def run_sync(
    taskdata: str | None = None, dry_run: bool = False, delete_tasks: bool = True
) -> bool:
    """Run the twcaldav sync.

    Args:
        taskdata: Optional TASKDATA path to use instead of default.
        dry_run: If True, run in dry-run mode.
        delete_tasks: If True, allow task deletion during sync.

    Returns:
        True if sync succeeded, False otherwise.
    """
    # Create config file
    config_path = Path("/tmp/twcaldav-test-config.toml")
    config_content = f"""[caldav]
url = "{CALDAV_URL.rstrip("/")}"
username = "{CALDAV_USERNAME}"
password = "{CALDAV_PASSWORD}"

[[mappings]]
taskwarrior_project = "{TW_PROJECT}"
caldav_calendar = "{CALDAV_CALENDAR_ID}"

[sync]
delete_tasks = {str(delete_tasks).lower()}
timezone = "{TIMEZONE}"
"""
    config_path.write_text(config_content)

    args = ["uv", "run", "twcaldav", "sync", "--config", str(config_path)]
    if dry_run:
        args.append("--dry-run")

    env = os.environ.copy()
    env["TZ"] = TIMEZONE
    taskdata_path = taskdata or TASKDATA
    if taskdata_path:
        env["TASKDATA"] = taskdata_path

    result = subprocess.run(args, cwd="/app" if Path("/app").exists() else ".", env=env)
    return result.returncode == 0


# Cleanup operations


def clear_taskwarrior(taskdata: str | None = None, project: str | None = None) -> None:
    """Clear all tasks from TaskWarrior test project.

    Args:
        taskdata: Optional TASKDATA path to use.
        project: Optional project to clear (defaults to TW_PROJECT).
    """
    proj = project or TW_PROJECT
    taskdata_path = taskdata or TASKDATA

    # Get all tasks (all statuses)
    cmd = [f"project:{proj}", "rc.verbose=nothing", "export"]
    stdout, _, _ = run_task_command(cmd, taskdata=taskdata_path)

    if stdout.strip():
        tasks_to_clear = json.loads(stdout)

        for task in tasks_to_clear:
            uuid = task.get("uuid")
            status = task.get("status", "")
            if uuid and status != "deleted":
                run_task_command(
                    ["rc.confirmation=off", "rc.verbose=nothing", uuid, "delete"],
                    taskdata=taskdata_path,
                )

    # Purge deleted tasks
    run_task_command(
        ["rc.confirmation=off", "rc.verbose=nothing", "purge"],
        taskdata=taskdata_path,
    )


def clear_caldav(calendar: caldav.Calendar) -> None:
    """Clear all todos from CalDAV calendar.

    Args:
        calendar: Calendar object.
    """
    todos = get_todos(calendar)
    for todo in todos:
        with contextlib.suppress(Exception):
            todo.delete()
