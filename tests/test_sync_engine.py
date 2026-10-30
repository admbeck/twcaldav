"""Tests for the sync engine module."""

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from twcaldav.caldav_client import CalDAVClient, VTodo
from twcaldav.config import (
    CalDAVConfig,
    Config,
    ProjectCalendarMapping,
    SyncConfig,
)
from twcaldav.sync_engine import (
    SyncAction,
    SyncDirection,
    SyncEngine,
    SyncStats,
    TaskPair,
)
from twcaldav.taskwarrior import Task, TaskWarrior


@pytest.fixture
def sample_config():
    """Create a sample configuration."""
    return Config(
        caldav=CalDAVConfig(
            url="https://caldav.example.com",
            username="testuser",
            password="testpass",
        ),
        mappings=[
            ProjectCalendarMapping(
                taskwarrior_project="work", caldav_calendar="Work Tasks"
            ),
            ProjectCalendarMapping(
                taskwarrior_project="personal", caldav_calendar="Personal Tasks"
            ),
        ],
        sync=SyncConfig(delete_tasks=True),
    )


@pytest.fixture
def mock_tw():
    """Create a mock TaskWarrior client."""
    return Mock(spec=TaskWarrior)


@pytest.fixture
def mock_caldav():
    """Create a mock CalDAV client."""
    return Mock(spec=CalDAVClient)


@pytest.fixture
def sync_engine(sample_config, mock_tw, mock_caldav):
    """Create a sync engine instance."""
    return SyncEngine(
        config=sample_config,
        tw=mock_tw,
        caldav_client=mock_caldav,
        dry_run=False,
    )


class TestSyncStats:
    """Tests for SyncStats dataclass."""

    def test_sync_stats_initialization(self) -> None:
        """Test that SyncStats initializes with zeros."""
        stats = SyncStats()
        assert stats.tw_created == 0
        assert stats.tw_updated == 0
        assert stats.tw_deleted == 0
        assert stats.caldav_created == 0
        assert stats.caldav_updated == 0
        assert stats.caldav_deleted == 0
        assert stats.skipped == 0
        assert stats.errors == 0

    def test_sync_stats_str(self) -> None:
        """Test SyncStats string representation."""
        stats = SyncStats(
            tw_created=2,
            tw_updated=3,
            tw_deleted=1,
            caldav_created=1,
            caldav_updated=2,
            caldav_deleted=1,
            skipped=5,
            errors=0,
        )
        result = str(stats)
        assert "TaskWarrior: 2 created, 3 updated, 1 deleted" in result
        assert "CalDAV: 1 created, 2 updated, 1 deleted" in result
        assert "Skipped: 5" in result
        assert "Errors: 0" in result


class TestTaskPair:
    """Tests for TaskPair dataclass."""

    def test_task_pair_creation(self) -> None:
        """Test TaskPair creation."""
        tw_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="pending",
            entry=datetime.now(),
        )
        pair = TaskPair(
            tw_task=tw_task,
            caldav_todo=None,
            action=SyncAction.CREATE,
            direction=SyncDirection.TW_TO_CALDAV,
            reason="New task",
        )
        assert pair.tw_task == tw_task
        assert pair.caldav_todo is None
        assert pair.action == SyncAction.CREATE
        assert pair.direction == SyncDirection.TW_TO_CALDAV
        assert pair.reason == "New task"


class TestSyncEngine:
    """Tests for SyncEngine class."""

    def test_init(self, sync_engine, sample_config, mock_tw, mock_caldav) -> None:
        """Test SyncEngine initialization."""
        assert sync_engine.config == sample_config
        assert sync_engine.tw == mock_tw
        assert sync_engine.caldav == mock_caldav
        assert sync_engine.dry_run is False

    def test_init_dry_run(self, sample_config, mock_tw, mock_caldav) -> None:
        """Test SyncEngine initialization with dry_run mode."""
        engine = SyncEngine(
            config=sample_config,
            tw=mock_tw,
            caldav_client=mock_caldav,
            dry_run=True,
        )
        assert engine.dry_run is True

    def test_discover_and_correlate_empty(
        self, sync_engine, mock_tw, mock_caldav
    ) -> None:
        """Test discovery with no tasks."""
        mock_tw.export_tasks.return_value = []
        mock_caldav.get_calendar.return_value = Mock()
        mock_caldav.get_todos.return_value = []

        pairs = sync_engine._discover_and_correlate()

        assert len(pairs) == 0
        # Should call export_tasks once for each mapped project (no status filter)
        assert mock_tw.export_tasks.call_count == 2

    def test_discover_and_correlate_tw_only(
        self, sync_engine, mock_tw, mock_caldav
    ) -> None:
        """Test discovery with TaskWarrior tasks only."""
        tw_task = Task(
            uuid="tw-123",
            description="Test task",
            status="pending",
            entry=datetime.now(),
            project="work",
        )
        mock_tw.export_tasks.return_value = [tw_task]
        mock_caldav.get_calendar.return_value = Mock()
        mock_caldav.get_todos.return_value = []

        pairs = sync_engine._discover_and_correlate()

        assert len(pairs) == 1
        assert pairs[0].tw_task == tw_task
        assert pairs[0].caldav_todo is None
        assert pairs[0].action == SyncAction.CREATE
        assert pairs[0].direction == SyncDirection.TW_TO_CALDAV

    def test_discover_and_correlate_caldav_only(
        self, sync_engine, mock_tw, mock_caldav
    ) -> None:
        """Test discovery with CalDAV todos only."""
        caldav_todo = VTodo(
            uid="cd-123",
            summary="Test todo",
            status="NEEDS-ACTION",
        )
        mock_tw.export_tasks.return_value = []
        mock_caldav.get_calendar.return_value = Mock()
        mock_caldav.get_todos.return_value = [caldav_todo]

        pairs = sync_engine._discover_and_correlate()

        assert len(pairs) == 1
        assert pairs[0].tw_task is None
        assert pairs[0].caldav_todo == caldav_todo
        assert pairs[0].action == SyncAction.CREATE
        assert pairs[0].direction == SyncDirection.CALDAV_TO_TW

    def test_discover_and_correlate_matched(
        self, sync_engine, mock_tw, mock_caldav
    ) -> None:
        """Test discovery with matched tasks (different content triggers update)."""
        now = datetime.now()
        tw_task = Task(
            uuid="tw-123",
            description="Test task",
            status="pending",
            entry=now,
            modified=now,
            project="work",
            caldav_uid="caldav-uid-123",
        )
        caldav_todo = VTodo(
            uid="caldav-uid-123",
            summary="Test todo",
            status="NEEDS-ACTION",
            last_modified=now,
        )

        mock_tw.export_tasks.return_value = [tw_task]
        mock_caldav.get_calendar.return_value = Mock()
        mock_caldav.get_todos.return_value = [caldav_todo]

        pairs = sync_engine._discover_and_correlate()

        assert len(pairs) == 1
        assert pairs[0].tw_task == tw_task
        assert pairs[0].caldav_todo == caldav_todo
        # Content differs (description != summary), so should update
        assert pairs[0].action == SyncAction.UPDATE
        assert pairs[0].direction == SyncDirection.CALDAV_TO_TW

    def test_classify_both_missing(self, sync_engine) -> None:
        """Test classification when both tasks are missing."""
        pair = sync_engine.classifier.classify(None, None)
        assert pair.action == SyncAction.SKIP
        assert "missing" in pair.reason.lower()

    def test_classify_tw_only_pending(self, sync_engine) -> None:
        """Test classification with pending TaskWarrior task only."""
        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="pending",
            entry=datetime.now(),
        )
        pair = sync_engine.classifier.classify(tw_task, None)
        assert pair.action == SyncAction.CREATE
        assert pair.direction == SyncDirection.TW_TO_CALDAV

    def test_classify_tw_only_deleted(self, sync_engine) -> None:
        """Test classification with deleted TaskWarrior task only."""
        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="deleted",
            entry=datetime.now(),
        )
        pair = sync_engine.classifier.classify(tw_task, None)
        assert pair.action == SyncAction.SKIP
        assert "deleted" in pair.reason.lower()

    def test_classify_caldav_only_active(self, sync_engine) -> None:
        """Test classification with active CalDAV todo only."""
        caldav_todo = VTodo(uid="cd-123", summary="Test", status="NEEDS-ACTION")
        pair = sync_engine.classifier.classify(None, caldav_todo)
        assert pair.action == SyncAction.CREATE
        assert pair.direction == SyncDirection.CALDAV_TO_TW

    def test_classify_caldav_only_cancelled(self, sync_engine) -> None:
        """Test classification with cancelled CalDAV todo only."""
        caldav_todo = VTodo(uid="cd-123", summary="Test", status="CANCELLED")
        pair = sync_engine.classifier.classify(None, caldav_todo)
        assert pair.action == SyncAction.SKIP
        assert "cancelled" in pair.reason.lower()

    def test_classify_both_deleted(self, sync_engine) -> None:
        """Test classification when both are deleted."""
        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="deleted",
            entry=datetime.now(),
        )
        caldav_todo = VTodo(uid="cd-123", summary="Test", status="CANCELLED")
        pair = sync_engine.classifier.classify(tw_task, caldav_todo)
        assert pair.action == SyncAction.SKIP
        assert "both deleted" in pair.reason.lower()

    def test_classify_tw_deleted_deletion_enabled(self, sync_engine) -> None:
        """Test classification when TW is deleted and deletion is enabled."""
        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="deleted",
            entry=datetime.now(),
        )
        caldav_todo = VTodo(uid="cd-123", summary="Test", status="NEEDS-ACTION")
        pair = sync_engine.classifier.classify(tw_task, caldav_todo)
        assert pair.action == SyncAction.DELETE
        assert pair.direction == SyncDirection.TW_TO_CALDAV

    def test_classify_tw_deleted_deletion_disabled(
        self, sample_config, mock_tw, mock_caldav
    ) -> None:
        """Test classification when TW is deleted and deletion is disabled.

        When delete_tasks=False, a deleted TW task should trigger an UPDATE
        to set the CalDAV todo to CANCELLED status (soft delete).
        """
        config = Config(
            caldav=sample_config.caldav,
            mappings=sample_config.mappings,
            sync=SyncConfig(delete_tasks=False),
        )
        engine = SyncEngine(config, mock_tw, mock_caldav, dry_run=False)

        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="deleted",
            entry=datetime.now(),
        )
        caldav_todo = VTodo(uid="cd-123", summary="Test", status="NEEDS-ACTION")
        pair = engine.classifier.classify(tw_task, caldav_todo)
        assert pair.action == SyncAction.UPDATE
        assert pair.direction == SyncDirection.TW_TO_CALDAV
        assert "cancelled" in pair.reason.lower()

    def test_classify_caldav_cancelled_deletion_enabled(self, sync_engine) -> None:
        """Test classification when CalDAV is cancelled and deletion is enabled."""
        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="pending",
            entry=datetime.now(),
        )
        caldav_todo = VTodo(uid="cd-123", summary="Test", status="CANCELLED")
        pair = sync_engine.classifier.classify(tw_task, caldav_todo)
        assert pair.action == SyncAction.DELETE
        assert pair.direction == SyncDirection.CALDAV_TO_TW

    def test_classify_tw_more_recent(self, sync_engine) -> None:
        """Test classification when TaskWarrior is more recent."""
        now = datetime.now()
        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="pending",
            entry=now - timedelta(hours=2),
            modified=now,
        )
        caldav_todo = VTodo(
            uid="cd-123",
            summary="Old",
            status="NEEDS-ACTION",
        )
        pair = sync_engine.classifier.classify(tw_task, caldav_todo)
        assert pair.action == SyncAction.UPDATE
        assert pair.direction == SyncDirection.TW_TO_CALDAV

    def test_classify_caldav_more_recent(self, sync_engine) -> None:
        """Test classification when CalDAV is more recent but content identical."""
        now = datetime.now()
        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="pending",
            entry=now - timedelta(hours=2),
            modified=now - timedelta(hours=1),
        )
        caldav_todo = VTodo(
            uid="cd-123",
            summary="Test",
            status="NEEDS-ACTION",
            last_modified=now,
        )
        pair = sync_engine.classifier.classify(tw_task, caldav_todo)
        # Content is identical, so skip despite timestamp difference
        assert pair.action == SyncAction.SKIP
        assert "content identical" in pair.reason.lower()

    def test_classify_caldav_no_timestamp(self, sync_engine) -> None:
        """Test classification when CalDAV lacks timestamp but content identical."""
        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="pending",
            entry=datetime.now(),
            modified=None,
        )
        caldav_todo = VTodo(
            uid="cd-123",
            summary="Test",
            status="NEEDS-ACTION",
            last_modified=None,
            created=None,
        )
        pair = sync_engine.classifier.classify(tw_task, caldav_todo)
        # Content is identical, so skip despite missing timestamps
        assert pair.action == SyncAction.SKIP
        assert "content identical" in pair.reason.lower()

    def test_classify_content_differs_lww(self, sync_engine) -> None:
        """Test classification when content differs - uses Last Write Wins."""
        now = datetime.now()
        tw_task = Task(
            uuid="tw-123",
            description="Old description",
            status="pending",
            entry=now - timedelta(hours=2),
            modified=now - timedelta(hours=1),
        )
        caldav_todo = VTodo(
            uid="cd-123",
            summary="New description",
            status="NEEDS-ACTION",
            last_modified=now,
        )
        pair = sync_engine.classifier.classify(tw_task, caldav_todo)
        # Content differs, CalDAV more recent - update TW from CalDAV
        assert pair.action == SyncAction.UPDATE
        assert pair.direction == SyncDirection.CALDAV_TO_TW
        assert "caldav more recent" in pair.reason.lower()

    def test_execute_sync_action_skip(self, sync_engine) -> None:
        """Test executing a SKIP action."""
        pair = TaskPair(
            tw_task=None,
            caldav_todo=None,
            action=SyncAction.SKIP,
            direction=None,
            reason="Test skip",
        )
        sync_engine._execute_sync_action(pair)
        assert sync_engine.stats.skipped == 1

    @patch("twcaldav.sync_engine.taskwarrior_to_caldav")
    def test_execute_create_tw_to_caldav(
        self, mock_convert, sync_engine, mock_caldav
    ) -> None:
        """Test executing CREATE from TaskWarrior to CalDAV."""
        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="pending",
            entry=datetime.now(),
            project="work",
        )
        pair = TaskPair(
            tw_task=tw_task,
            caldav_todo=None,
            action=SyncAction.CREATE,
            direction=SyncDirection.TW_TO_CALDAV,
            reason="New task",
        )

        mock_vtodo = VTodo(uid="new-uid", summary="Test")
        mock_convert.return_value = mock_vtodo

        sync_engine._execute_create(pair)

        mock_convert.assert_called_once_with(tw_task)
        mock_caldav.create_todo.assert_called_once_with("Work Tasks", mock_vtodo)
        assert sync_engine.stats.caldav_created == 1

    @patch("twcaldav.sync_engine.caldav_to_taskwarrior")
    def test_execute_create_caldav_to_tw(
        self, mock_convert, sync_engine, mock_tw
    ) -> None:
        """Test executing CREATE from CalDAV to TaskWarrior."""
        caldav_todo = VTodo(uid="cd-123", summary="Test", status="NEEDS-ACTION")
        pair = TaskPair(
            tw_task=None,
            caldav_todo=caldav_todo,
            action=SyncAction.CREATE,
            direction=SyncDirection.CALDAV_TO_TW,
            reason="New todo",
        )

        mock_task = Task(
            uuid="new-uuid",
            description="Test",
            status="pending",
            entry=datetime.now(),
        )
        mock_convert.return_value = mock_task

        sync_engine._execute_create(pair)

        mock_convert.assert_called_once_with(caldav_todo)
        mock_tw.create_task.assert_called_once_with(mock_task)
        assert sync_engine.stats.tw_created == 1

    @patch("twcaldav.sync_engine.taskwarrior_to_caldav")
    def test_execute_update_tw_to_caldav(
        self, mock_convert, sync_engine, mock_caldav
    ) -> None:
        """Test executing UPDATE from TaskWarrior to CalDAV."""
        tw_task = Task(
            uuid="tw-123",
            description="Updated",
            status="pending",
            entry=datetime.now(),
            project="work",
        )
        caldav_todo = VTodo(
            uid="cd-123",
            summary="Old",
            status="NEEDS-ACTION",
        )
        pair = TaskPair(
            tw_task=tw_task,
            caldav_todo=caldav_todo,
            action=SyncAction.UPDATE,
            direction=SyncDirection.TW_TO_CALDAV,
            reason="TW more recent",
        )

        mock_vtodo = VTodo(uid="new-uid", summary="Updated")
        mock_convert.return_value = mock_vtodo
        mock_calendar = Mock()
        mock_caldav.get_calendar.return_value = mock_calendar

        sync_engine._execute_update(pair)

        mock_convert.assert_called_once_with(tw_task, existing_description=None)
        assert mock_vtodo.uid == "cd-123"  # UID should be preserved
        mock_caldav.update_todo.assert_called_once()
        assert sync_engine.stats.caldav_updated == 1

    @patch("twcaldav.sync_engine.caldav_to_taskwarrior")
    def test_execute_update_caldav_to_tw(
        self, mock_convert, sync_engine, mock_tw
    ) -> None:
        """Test executing UPDATE from CalDAV to TaskWarrior."""
        tw_task = Task(
            uuid="tw-123",
            description="Old",
            status="pending",
            entry=datetime.now(),
        )
        caldav_todo = VTodo(
            uid="cd-123",
            summary="Updated",
            status="NEEDS-ACTION",
        )
        pair = TaskPair(
            tw_task=tw_task,
            caldav_todo=caldav_todo,
            action=SyncAction.UPDATE,
            direction=SyncDirection.CALDAV_TO_TW,
            reason="CalDAV more recent",
        )

        mock_task = Task(
            uuid="new-uuid",
            description="Updated",
            status="pending",
            entry=datetime.now(),
        )
        mock_convert.return_value = mock_task

        sync_engine._execute_update(pair)

        # Should pass existing_task for annotation deduplication
        mock_convert.assert_called_once_with(caldav_todo, existing_task=tw_task)
        assert mock_task.uuid == "tw-123"  # UUID should be preserved
        assert mock_task.entry == tw_task.entry  # Entry should be preserved
        # Should use import_tasks instead of modify_task for proper annotation handling
        mock_tw.import_tasks.assert_called_once()
        assert sync_engine.stats.tw_updated == 1

    def test_execute_delete_tw_to_caldav(self, sync_engine, mock_caldav) -> None:
        """Test executing DELETE from TaskWarrior to CalDAV."""
        tw_task = Task(
            uuid="tw-123",
            description="Deleted",
            status="deleted",
            entry=datetime.now(),
            project="work",
        )
        caldav_todo = VTodo(
            uid="cd-123",
            summary="Old",
            status="NEEDS-ACTION",
        )
        pair = TaskPair(
            tw_task=tw_task,
            caldav_todo=caldav_todo,
            action=SyncAction.DELETE,
            direction=SyncDirection.TW_TO_CALDAV,
            reason="TW deleted",
        )

        sync_engine._execute_delete(pair)

        mock_caldav.delete_todo.assert_called_once_with("Work Tasks", "cd-123")
        assert sync_engine.stats.caldav_deleted == 1

    def test_execute_delete_caldav_to_tw(self, sync_engine, mock_tw) -> None:
        """Test executing DELETE from CalDAV to TaskWarrior."""
        tw_task = Task(
            uuid="tw-123",
            description="Old",
            status="pending",
            entry=datetime.now(),
        )
        caldav_todo = VTodo(
            uid="cd-123",
            summary="Deleted",
            status="CANCELLED",
        )
        pair = TaskPair(
            tw_task=tw_task,
            caldav_todo=caldav_todo,
            action=SyncAction.DELETE,
            direction=SyncDirection.CALDAV_TO_TW,
            reason="CalDAV cancelled",
        )

        sync_engine._execute_delete(pair)

        mock_tw.delete_task.assert_called_once_with("tw-123")
        assert sync_engine.stats.tw_deleted == 1

    def test_execute_cancel_caldav(self, sync_engine, mock_caldav) -> None:
        """Test executing UPDATE that sets CalDAV todo to CANCELLED.

        When TW task is deleted and delete_tasks=False, the sync should
        set the CalDAV todo to CANCELLED status instead of deleting it.
        """
        tw_task = Task(
            uuid="tw-123",
            description="Deleted task",
            status="deleted",
            entry=datetime.now(),
            project="work",
        )
        caldav_todo = VTodo(
            uid="cd-123",
            summary="Deleted task",
            status="NEEDS-ACTION",
        )
        pair = TaskPair(
            tw_task=tw_task,
            caldav_todo=caldav_todo,
            action=SyncAction.UPDATE,
            direction=SyncDirection.TW_TO_CALDAV,
            reason="TaskWarrior task deleted, setting CalDAV to CANCELLED",
        )

        sync_engine._execute_update(pair)

        # Should call cancel_todo instead of update_todo
        mock_caldav.cancel_todo.assert_called_once_with("Work Tasks", "cd-123")
        mock_caldav.update_todo.assert_not_called()
        assert sync_engine.stats.caldav_updated == 1

    def test_dry_run_no_changes(self, sample_config, mock_tw, mock_caldav) -> None:
        """Test that dry-run mode makes no actual changes."""
        engine = SyncEngine(sample_config, mock_tw, mock_caldav, dry_run=True)

        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="pending",
            entry=datetime.now(),
            project="work",
        )
        pair = TaskPair(
            tw_task=tw_task,
            caldav_todo=None,
            action=SyncAction.CREATE,
            direction=SyncDirection.TW_TO_CALDAV,
            reason="New task",
        )

        engine._execute_create(pair)

        # Should not call caldav.create_todo in dry-run mode
        mock_caldav.create_todo.assert_not_called()
        # But stats should still be updated
        assert engine.stats.caldav_created == 1

    def test_sync_integration(self, sync_engine, mock_tw, mock_caldav) -> None:
        """Test full sync integration."""
        tw_task = Task(
            uuid="tw-123",
            description="Test",
            status="pending",
            entry=datetime.now(),
            project="work",
        )
        mock_tw.export_tasks.return_value = [tw_task]
        mock_caldav.get_calendar.return_value = Mock()
        mock_caldav.get_todos.return_value = []

        with patch("twcaldav.sync_engine.taskwarrior_to_caldav") as mock_convert:
            mock_vtodo = VTodo(uid="new-uid", summary="Test")
            mock_convert.return_value = mock_vtodo

            stats = sync_engine.sync()

            assert stats.caldav_created == 1
            assert stats.errors == 0

    def test_sync_with_error(self, sync_engine, mock_tw, mock_caldav) -> None:
        """Test sync with error during discovery."""
        mock_tw.export_tasks.side_effect = RuntimeError("TaskWarrior error")

        with pytest.raises(RuntimeError, match="TaskWarrior error"):
            sync_engine.sync()

        assert sync_engine.stats.errors == 1
