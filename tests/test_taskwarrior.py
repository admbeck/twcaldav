"""Tests for TaskWarrior module."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import Mock, patch

import pytest

from twcaldav.taskwarrior import Task, TaskWarrior, TaskWarriorError


class TestTask:
    """Tests for Task dataclass."""

    def test_from_dict_minimal(self) -> None:
        """Test creating Task from minimal dictionary."""
        data = {
            "uuid": "12345678-1234-1234-1234-123456789012",
            "description": "Test task",
            "status": "pending",
            "entry": "20241117T100000Z",
        }

        task = Task.from_dict(data)

        assert task.uuid == "12345678-1234-1234-1234-123456789012"
        assert task.description == "Test task"
        assert task.status == "pending"
        assert task.entry == datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC)
        assert task.modified is None
        assert task.project is None
        assert task.due is None
        assert task.priority is None
        assert task.tags is None
        assert task.annotations is None

    def test_from_dict_full(self) -> None:
        """Test creating Task from complete dictionary."""
        data = {
            "uuid": "12345678-1234-1234-1234-123456789012",
            "description": "Complete task",
            "status": "pending",
            "entry": "20241117T100000Z",
            "modified": "20241117T110000Z",
            "project": "work",
            "due": "20241120T120000Z",
            "priority": "H",
            "tags": ["important", "urgent"],
            "annotations": [{"entry": "20241117T103000Z", "description": "First note"}],
        }

        task = Task.from_dict(data)

        assert task.uuid == "12345678-1234-1234-1234-123456789012"
        assert task.description == "Complete task"
        assert task.status == "pending"
        assert task.project == "work"
        assert task.due == datetime(2024, 11, 20, 12, 0, 0, tzinfo=UTC)
        assert task.priority == "H"
        assert task.tags == ["important", "urgent"]
        assert len(task.annotations) == 1

    def test_to_dict_minimal(self) -> None:
        """Test converting minimal Task to dictionary."""
        task = Task(
            uuid="12345678-1234-1234-1234-123456789012",
            description="Test task",
            status="pending",
            entry=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
        )

        data = task.to_dict()

        assert data["uuid"] == "12345678-1234-1234-1234-123456789012"
        assert data["description"] == "Test task"
        assert data["status"] == "pending"
        assert data["entry"] == "20241117T100000Z"
        assert "modified" not in data
        assert "project" not in data

    def test_to_dict_full(self) -> None:
        """Test converting complete Task to dictionary."""
        task = Task(
            uuid="12345678-1234-1234-1234-123456789012",
            description="Complete task",
            status="pending",
            entry=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
            modified=datetime(2024, 11, 17, 11, 0, 0, tzinfo=UTC),
            project="work",
            due=datetime(2024, 11, 20, 12, 0, 0, tzinfo=UTC),
            priority="H",
            tags=["important", "urgent"],
            annotations=[{"entry": "20241117T103000Z", "description": "First note"}],
        )

        data = task.to_dict()

        assert data["uuid"] == "12345678-1234-1234-1234-123456789012"
        assert data["project"] == "work"
        assert data["due"] == "20241120T120000Z"
        assert data["priority"] == "H"
        assert data["tags"] == ["important", "urgent"]
        assert len(data["annotations"]) == 1

    def test_to_dict_converts_times_to_utc(self) -> None:
        """A time with a timezone is written as the same instant in UTC."""
        task = Task(
            uuid="12345678-1234-1234-1234-123456789012",
            description="Haircut",
            status="pending",
            entry=datetime(2025, 8, 1, 0, 0, 0, tzinfo=UTC),
            due=datetime(2025, 8, 15, 12, 30, 1, tzinfo=ZoneInfo("Asia/Tashkent")),
            scheduled=datetime(2025, 8, 15, 9, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
        )

        data = task.to_dict()

        assert data["due"] == "20250815T073001Z"
        assert data["scheduled"] == "20250815T070000Z"

    def test_to_dict_keeps_naive_times(self) -> None:
        """A time without a timezone (date-only or floating) counts as UTC."""
        task = Task(
            uuid="12345678-1234-1234-1234-123456789012",
            description="Task",
            status="pending",
            entry=datetime(2025, 8, 1, 0, 0, 0, tzinfo=UTC),
            due=datetime(2025, 8, 15, 0, 0, 0),
        )

        assert task.to_dict()["due"] == "20250815T000000Z"

    def test_from_dict_keeps_unmapped_fields(self) -> None:
        """Fields twcaldav doesn't model are kept in extra."""
        data = {
            "uuid": "12345678-1234-1234-1234-123456789012",
            "description": "Task",
            "status": "pending",
            "entry": "20241117T100000Z",
            "start": "20241117T103000Z",
            "depends": ["87654321-4321-4321-4321-210987654321"],
            "estimate": "2h",
        }

        task = Task.from_dict(data)

        assert task.extra == {
            "start": "20241117T103000Z",
            "depends": ["87654321-4321-4321-4321-210987654321"],
            "estimate": "2h",
        }

    def test_from_dict_drops_computed_fields(self) -> None:
        """The id and urgency columns of an export are not kept."""
        data = {
            "id": 3,
            "uuid": "12345678-1234-1234-1234-123456789012",
            "description": "Task",
            "status": "pending",
            "entry": "20241117T100000Z",
            "urgency": 4.2,
        }

        task = Task.from_dict(data)

        assert task.extra == {}

    def test_to_dict_writes_unmapped_fields(self) -> None:
        """A from_dict/to_dict round trip keeps fields twcaldav doesn't model."""
        data = {
            "uuid": "12345678-1234-1234-1234-123456789012",
            "description": "Task",
            "status": "pending",
            "entry": "20241117T100000Z",
            "start": "20241117T103000Z",
            "depends": ["87654321-4321-4321-4321-210987654321"],
        }

        result = Task.from_dict(data).to_dict()

        assert result["start"] == "20241117T103000Z"
        assert result["depends"] == ["87654321-4321-4321-4321-210987654321"]


class TestTaskWarrior:
    """Tests for TaskWarrior class."""

    @patch("subprocess.run")
    def test_init_success(self, mock_run) -> None:
        """Test successful initialization."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)

        tw = TaskWarrior()

        assert tw.task_bin == "task"
        assert tw.taskdata is None
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_init_binary_not_found(self, mock_run) -> None:
        """Test initialization when binary is not found."""
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(TaskWarriorError, match="binary not found"):
            TaskWarrior()

    @patch("subprocess.run")
    def test_init_custom_binary(self, mock_run) -> None:
        """Test initialization with custom binary path."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)

        tw = TaskWarrior(task_bin="/usr/local/bin/task")

        assert tw.task_bin == "/usr/local/bin/task"

    @patch("subprocess.run")
    def test_init_with_taskdata(self, mock_run) -> None:
        """Test initialization with custom TASKDATA."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)

        tw = TaskWarrior(taskdata=Path("/tmp/taskdata"))

        assert tw.taskdata == Path("/tmp/taskdata")

    @patch("subprocess.run")
    def test_export_tasks_empty(self, mock_run) -> None:
        """Test exporting when no tasks match."""
        # First call for init check
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        # Second call for export
        mock_run.return_value = Mock(stdout="", returncode=0)
        tasks = tw.export_tasks()

        assert tasks == []

    @patch("subprocess.run")
    def test_export_tasks_single(self, mock_run) -> None:
        """Test exporting a single task."""
        # First call for init
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        # Second call for export
        task_json = json.dumps(
            [
                {
                    "uuid": "12345678-1234-1234-1234-123456789012",
                    "description": "Test task",
                    "status": "pending",
                    "entry": "20241117T100000Z",
                }
            ]
        )
        mock_run.return_value = Mock(stdout=task_json, returncode=0)

        tasks = tw.export_tasks()

        assert len(tasks) == 1
        assert tasks[0].uuid == "12345678-1234-1234-1234-123456789012"
        assert tasks[0].description == "Test task"

    @patch("subprocess.run")
    def test_export_tasks_with_project_filter(self, mock_run) -> None:
        """Test exporting tasks filtered by project."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        task_json = json.dumps(
            [
                {
                    "uuid": "12345678-1234-1234-1234-123456789012",
                    "description": "Work task",
                    "status": "pending",
                    "entry": "20241117T100000Z",
                    "project": "work",
                }
            ]
        )
        mock_run.return_value = Mock(stdout=task_json, returncode=0)

        tasks = tw.export_tasks(project="work")

        assert len(tasks) == 1
        assert tasks[0].project == "work"
        # Check that project filter was used
        call_args = mock_run.call_args[0][0]
        assert "project:work" in call_args

    @patch("subprocess.run")
    def test_export_tasks_with_status_filter(self, mock_run) -> None:
        """Test exporting tasks filtered by status."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        task_json = json.dumps(
            [
                {
                    "uuid": "12345678-1234-1234-1234-123456789012",
                    "description": "Completed task",
                    "status": "completed",
                    "entry": "20241117T100000Z",
                }
            ]
        )
        mock_run.return_value = Mock(stdout=task_json, returncode=0)

        tasks = tw.export_tasks(status="completed")

        assert len(tasks) == 1
        assert tasks[0].status == "completed"
        # Check that status filter was used
        call_args = mock_run.call_args[0][0]
        assert "status:completed" in call_args

    @patch("subprocess.run")
    def test_export_tasks_json_decode_error(self, mock_run) -> None:
        """Test handling of invalid JSON from TaskWarrior."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        mock_run.return_value = Mock(stdout="invalid json", returncode=0)

        with pytest.raises(TaskWarriorError, match="Failed to parse"):
            tw.export_tasks()

    @patch("subprocess.run")
    def test_import_tasks(self, mock_run) -> None:
        """Test importing tasks."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        tasks = [
            Task(
                uuid="12345678-1234-1234-1234-123456789012",
                description="New task",
                status="pending",
                entry=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
            )
        ]

        mock_run.return_value = Mock(stdout="", returncode=0)
        tw.import_tasks(tasks)

        # Check that import was called with correct JSON
        call_args = mock_run.call_args
        assert call_args[0][0][-1] == "import"
        assert call_args[1]["input"] is not None

    @patch("subprocess.run")
    def test_import_tasks_empty(self, mock_run) -> None:
        """Test importing empty task list."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        tw.import_tasks([])

        # Should only have been called once (for init)
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    def test_create_task(self, mock_run) -> None:
        """Test creating a single task."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        task = Task(
            uuid="12345678-1234-1234-1234-123456789012",
            description="New task",
            status="pending",
            entry=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
        )

        mock_run.return_value = Mock(stdout="", returncode=0)
        tw.create_task(task)

        # Should have called import
        call_args = mock_run.call_args[0][0]
        assert "import" in call_args

    @patch("subprocess.run")
    def test_modify_task(self, mock_run) -> None:
        """Test modifying a task."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        mock_run.return_value = Mock(stdout="", returncode=0)
        tw.modify_task(
            "12345678-1234-1234-1234-123456789012",
            {"description": "Updated task", "priority": "H"},
        )

        # Check that modify command was called correctly
        call_args = mock_run.call_args[0][0]
        assert "modify" in call_args
        assert "12345678-1234-1234-1234-123456789012" in call_args
        assert any("description:" in arg for arg in call_args)
        assert any("priority:" in arg for arg in call_args)

    @patch("subprocess.run")
    def test_delete_task(self, mock_run) -> None:
        """Test deleting a task."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        mock_run.return_value = Mock(stdout="", returncode=0)
        tw.delete_task("12345678-1234-1234-1234-123456789012")

        # Check that delete command was called
        call_args = mock_run.call_args[0][0]
        assert "delete" in call_args
        assert "12345678-1234-1234-1234-123456789012" in call_args
        assert "rc.confirmation=off" in call_args

    @patch("subprocess.run")
    def test_add_annotation(self, mock_run) -> None:
        """Test adding an annotation."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        mock_run.return_value = Mock(stdout="", returncode=0)
        tw.add_annotation("12345678-1234-1234-1234-123456789012", "Test annotation")

        # Check that annotate command was called
        call_args = mock_run.call_args[0][0]
        assert "annotate" in call_args
        assert "12345678-1234-1234-1234-123456789012" in call_args
        assert "Test annotation" in call_args

    @patch("subprocess.run")
    def test_get_task_by_uuid(self, mock_run) -> None:
        """Test getting a specific task by UUID."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        task_json = json.dumps(
            [
                {
                    "uuid": "12345678-1234-1234-1234-123456789012",
                    "description": "Test task",
                    "status": "pending",
                    "entry": "20241117T100000Z",
                }
            ]
        )
        mock_run.return_value = Mock(stdout=task_json, returncode=0)

        task = tw.get_task_by_uuid("12345678-1234-1234-1234-123456789012")

        assert task is not None
        assert task.uuid == "12345678-1234-1234-1234-123456789012"

    @patch("subprocess.run")
    def test_get_task_by_uuid_not_found(self, mock_run) -> None:
        """Test getting a non-existent task."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        mock_run.return_value = Mock(stdout="", returncode=0)
        task = tw.get_task_by_uuid("nonexistent-uuid")

        assert task is None

    @patch("subprocess.run")
    def test_get_tasks_by_project(self, mock_run) -> None:
        """Test getting tasks by project."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        task_json = json.dumps(
            [
                {
                    "uuid": "12345678-1234-1234-1234-123456789012",
                    "description": "Work task",
                    "status": "pending",
                    "entry": "20241117T100000Z",
                    "project": "work",
                }
            ]
        )
        mock_run.return_value = Mock(stdout=task_json, returncode=0)

        tasks = tw.get_tasks_by_project("work")

        assert len(tasks) == 1
        assert tasks[0].project == "work"

    @patch("subprocess.run")
    def test_command_failure(self, mock_run) -> None:
        """Test handling of command failure."""
        mock_run.return_value = Mock(stdout="3.0.0", returncode=0)
        tw = TaskWarrior()

        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["task", "export"], stderr="Error occurred"
        )

        with pytest.raises(TaskWarriorError, match="command failed"):
            tw.export_tasks()
