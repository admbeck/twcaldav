"""TaskWarrior integration module."""

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from twcaldav.logger import get_logger

# Export fields Task models itself.
_MAPPED_FIELDS = frozenset(
    {
        "uuid",
        "description",
        "status",
        "entry",
        "modified",
        "project",
        "due",
        "scheduled",
        "wait",
        "end",
        "priority",
        "tags",
        "annotations",
        "caldav_uid",
    }
)

# Export fields TaskWarrior computes; they can't be imported.
_COMPUTED_FIELDS = frozenset({"id", "urgency"})


@dataclass
class Task:
    """Represents a TaskWarrior task."""

    uuid: str
    description: str
    status: str
    entry: datetime
    modified: datetime | None = None
    project: str | None = None
    due: datetime | None = None
    scheduled: datetime | None = None
    wait: datetime | None = None
    end: datetime | None = None
    priority: str | None = None
    tags: list[str] | None = None
    annotations: list[dict[str, Any]] | None = None
    caldav_uid: str | None = None
    # Fields twcaldav doesn't model (start, depends, recur, other UDAs...).
    # TaskWarrior import replaces the whole task, so they are written back.
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Create Task from TaskWarrior JSON export dictionary.

        Args:
            data: Task data from TaskWarrior JSON export.

        Returns:
            Task instance.
        """
        # Parse timestamps
        entry = datetime.fromisoformat(data["entry"])
        modified = None
        if "modified" in data:
            modified = datetime.fromisoformat(data["modified"])
        due = None
        if "due" in data:
            due = datetime.fromisoformat(data["due"])
        scheduled = None
        if "scheduled" in data:
            scheduled = datetime.fromisoformat(data["scheduled"])
        wait = None
        if "wait" in data:
            wait = datetime.fromisoformat(data["wait"])
        end = None
        if "end" in data:
            end = datetime.fromisoformat(data["end"])

        return cls(
            uuid=data["uuid"],
            description=data["description"],
            status=data["status"],
            entry=entry,
            modified=modified,
            project=data.get("project"),
            due=due,
            scheduled=scheduled,
            wait=wait,
            end=end,
            priority=data.get("priority"),
            tags=data.get("tags"),
            annotations=data.get("annotations"),
            caldav_uid=data.get("caldav_uid"),
            extra={
                key: value
                for key, value in data.items()
                if key not in _MAPPED_FIELDS and key not in _COMPUTED_FIELDS
            },
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert Task to TaskWarrior JSON format.

        Returns:
            Dictionary suitable for TaskWarrior import.
        """
        data: dict[str, Any] = {
            **self.extra,
            "uuid": self.uuid,
            "description": self.description,
            "status": self.status,
            "entry": self.entry.strftime("%Y%m%dT%H%M%SZ"),
        }

        if self.modified:
            data["modified"] = self.modified.strftime("%Y%m%dT%H%M%SZ")
        if self.project:
            data["project"] = self.project
        if self.due:
            data["due"] = self.due.strftime("%Y%m%dT%H%M%SZ")
        if self.scheduled:
            data["scheduled"] = self.scheduled.strftime("%Y%m%dT%H%M%SZ")
        if self.wait:
            data["wait"] = self.wait.strftime("%Y%m%dT%H%M%SZ")
        if self.end:
            data["end"] = self.end.strftime("%Y%m%dT%H%M%SZ")
        if self.priority:
            data["priority"] = self.priority
        if self.tags:
            data["tags"] = self.tags
        if self.annotations:
            data["annotations"] = self.annotations
        if self.caldav_uid:
            data["caldav_uid"] = self.caldav_uid

        return data


class TaskWarriorError(Exception):
    """Exception raised for TaskWarrior-related errors."""


class TaskWarrior:
    """Interface to TaskWarrior via the task binary."""

    def __init__(self, task_bin: str = "task", taskdata: Path | None = None) -> None:
        """Initialize TaskWarrior interface.

        Args:
            task_bin: Path to task binary (default: "task").
            taskdata: Path to TaskWarrior data directory (optional).
                     If provided, sets TASKDATA environment variable.

        Raises:
            TaskWarriorError: If task binary is not found.
        """
        self.task_bin = task_bin
        self.taskdata = taskdata
        self.logger = get_logger()

        # Verify task binary exists
        try:
            self._run_command(["version"], check_binary=False)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            raise TaskWarriorError(
                f"TaskWarrior binary '{task_bin}' not found or not executable"
            ) from e

    def _run_command(
        self, args: list[str], input_data: str | None = None, check_binary: bool = True
    ) -> str:
        """Run a TaskWarrior command.

        Args:
            args: Command arguments (without 'task' prefix).
            input_data: Optional input data to pass via stdin.
            check_binary: Whether this is being called to check binary existence.

        Returns:
            Command output (stdout).

        Raises:
            TaskWarriorError: If command fails.
        """
        import os

        # Determine taskdata location from self.taskdata or TASKDATA env var
        taskdata_path = None
        if self.taskdata:
            taskdata_path = str(self.taskdata)
        elif "TASKDATA" in os.environ:
            taskdata_path = os.environ["TASKDATA"]

        # Build command with rc.data.location if taskdata is specified
        cmd_args = list(args)
        if taskdata_path and not check_binary:
            # Insert rc.data.location as first argument (after 'task')
            cmd_args.insert(0, f"rc.data.location={taskdata_path}")

        cmd = [self.task_bin, *cmd_args]
        env = None

        # Also set TASKDATA environment variable for compatibility
        if taskdata_path:
            env = os.environ.copy()
            env["TASKDATA"] = taskdata_path

        if not check_binary:
            self.logger.debug(f"Running TaskWarrior command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                input=input_data,
                env=env,
                check=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            if not check_binary:
                error_msg = f"TaskWarrior command failed with exit code {e.returncode}"
                if e.stderr:
                    error_msg += f"\nSTDERR: {e.stderr}"
                if e.stdout:
                    error_msg += f"\nSTDOUT: {e.stdout}"
                if input_data:
                    error_msg += (
                        f"\nINPUT DATA: {input_data[:500]}..."  # First 500 chars
                    )
                self.logger.error(error_msg)
            raise TaskWarriorError(
                f"TaskWarrior command failed: {e.stderr or e.stdout}"
            ) from e
        except FileNotFoundError as e:
            raise TaskWarriorError(
                f"TaskWarrior binary not found: {self.task_bin}"
            ) from e

    def export_tasks(
        self,
        filter_args: list[str] | None = None,
        status: str | None = None,
        project: str | None = None,
    ) -> list[Task]:
        """Export tasks from TaskWarrior.

        Args:
            filter_args: Additional filter arguments for task command.
            status: Filter by status (pending, completed, deleted, etc.).
            project: Filter by project name.

        Returns:
            List of Task objects.

        Raises:
            TaskWarriorError: If export fails.
        """
        cmd_args = []

        if status:
            cmd_args.append(f"status:{status}")
        if project:
            cmd_args.append(f"project:{project}")
        if filter_args:
            cmd_args.extend(filter_args)

        cmd_args.extend(["export"])

        self.logger.debug(f"Exporting tasks with filters: {cmd_args}")

        output = self._run_command(cmd_args)

        if not output.strip():
            self.logger.debug("No tasks found matching filter")
            return []

        try:
            tasks_data = json.loads(output)
            tasks = [Task.from_dict(task_data) for task_data in tasks_data]
            self.logger.debug(f"Exported {len(tasks)} tasks")
            return tasks
        except json.JSONDecodeError as e:
            raise TaskWarriorError(
                f"Failed to parse TaskWarrior JSON output: {e}"
            ) from e
        except KeyError as e:
            raise TaskWarriorError(f"Missing required field in task data: {e}") from e

    def import_tasks(self, tasks: list[Task]) -> None:
        """Import tasks into TaskWarrior.

        This allows creating tasks with pre-assigned UUIDs.

        Args:
            tasks: List of Task objects to import.

        Raises:
            TaskWarriorError: If import fails.
        """
        if not tasks:
            self.logger.debug("No tasks to import")
            return

        tasks_json = json.dumps([task.to_dict() for task in tasks])

        self.logger.info(f"Importing {len(tasks)} tasks")
        self.logger.info(f"JSON being imported (first 500 chars): {tasks_json[:500]}")
        self._run_command(["import"], input_data=tasks_json)
        self.logger.info(f"Imported {len(tasks)} tasks")

    def create_task(self, task: Task) -> None:
        """Create a single task in TaskWarrior.

        Uses import to allow pre-assigned UUID.

        Args:
            task: Task object to create.

        Raises:
            TaskWarriorError: If creation fails.
        """
        self.import_tasks([task])

    def modify_task(self, uuid: str, modifications: dict[str, Any]) -> None:
        """Modify an existing task.

        Args:
            uuid: UUID of task to modify.
            modifications: Dictionary of field modifications.

        Raises:
            TaskWarriorError: If modification fails.
        """
        cmd_args = [uuid, "modify"]

        for key, value in modifications.items():
            if value is None:
                # Remove the attribute
                cmd_args.append(f"{key}:")
            elif isinstance(value, list):
                # For tags
                cmd_args.append(f"{key}:{','.join(value)}")
            elif isinstance(value, datetime):
                # For dates
                cmd_args.append(f"{key}:{value.strftime('%Y%m%dT%H%M%SZ')}")
            else:
                cmd_args.append(f"{key}:{value}")

        self.logger.debug(f"Modifying task {uuid}: {modifications}")
        # Add rc.confirmation=off to skip confirmation prompts
        self._run_command(["rc.confirmation=off", *cmd_args])
        self.logger.info(f"Modified task {uuid}")

    def delete_task(self, uuid: str) -> None:
        """Delete a task.

        Args:
            uuid: UUID of task to delete.

        Raises:
            TaskWarriorError: If deletion fails.
        """
        self.logger.debug(f"Deleting task {uuid}")
        # Add rc.confirmation=off to skip confirmation prompts
        self._run_command(["rc.confirmation=off", uuid, "delete"])
        self.logger.info(f"Deleted task {uuid}")

    def add_annotation(self, uuid: str, annotation: str) -> None:
        """Add an annotation to a task.

        Args:
            uuid: UUID of task.
            annotation: Annotation text to add.

        Raises:
            TaskWarriorError: If adding annotation fails.
        """
        self.logger.debug(f"Adding annotation to task {uuid}")
        self._run_command(["rc.confirmation=off", uuid, "annotate", annotation])
        self.logger.info(f"Added annotation to task {uuid}")

    def get_task_by_uuid(self, uuid: str) -> Task | None:
        """Get a specific task by UUID.

        Args:
            uuid: UUID of task to retrieve.

        Returns:
            Task object if found, None otherwise.

        Raises:
            TaskWarriorError: If query fails.
        """
        tasks = self.export_tasks(filter_args=[uuid])
        return tasks[0] if tasks else None

    def get_tasks_by_project(self, project: str, status: str = "pending") -> list[Task]:
        """Get all tasks in a specific project.

        Args:
            project: Project name.
            status: Task status to filter by (default: "pending").

        Returns:
            List of Task objects.

        Raises:
            TaskWarriorError: If query fails.
        """
        return self.export_tasks(project=project, status=status)

    def get_task_by_caldav_uid(self, caldav_uid: str) -> Task | None:
        """Get a task by CalDAV UID (UDA).

        Args:
            caldav_uid: CalDAV UID to search for.

        Returns:
            Task object if found, None otherwise.

        Raises:
            TaskWarriorError: If query fails.
        """
        tasks = self.export_tasks(filter_args=[f"caldav_uid:{caldav_uid}"])
        return tasks[0] if tasks else None

    def validate_uda(self, uda_name: str) -> bool:
        """Validate that a UDA is configured in TaskWarrior.

        Args:
            uda_name: Name of the UDA to check (e.g., "caldav_uid").

        Returns:
            True if UDA is configured, False otherwise.

        Raises:
            TaskWarriorError: If command fails.
        """
        try:
            result = self._run_command(["udas"])
            # Check if the UDA name appears in the output
            return uda_name in result
        except TaskWarriorError:
            return False
