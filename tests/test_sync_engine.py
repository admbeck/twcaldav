"""Tests for the sync engine module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from twcaldav.caldav_client import CalDAVClient, VTodo
from twcaldav.config import (
    CalDAVConfig,
    Config,
    ProjectCalendarMapping,
    SyncConfig,
)
from twcaldav.field_mapper import note_entry, taskwarrior_to_caldav
from twcaldav.sync_engine import (
    SyncAction,
    SyncDirection,
    SyncEngine,
    SyncStats,
    TaskPair,
)
from twcaldav.sync_merge import (
    decode_base,
    encode_base,
    snapshot_from_task,
    snapshot_from_todo,
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


def _synced_pair(**fields: object) -> tuple[Task, VTodo]:
    """Return a task and its todo as left by a sync, with a recorded base."""
    entry = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
    task = Task(
        uuid="tw-123",
        description="Pay rent",
        status="pending",
        entry=entry,
        modified=datetime(2026, 1, 2, 9, 0, 0, tzinfo=UTC),
        project="work",
        due=datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC),
        annotations=[{"entry": note_entry(entry), "description": "Account 123"}],
        caldav_uid="cd-123",
    )
    for name, value in fields.items():
        setattr(task, name, value)
    todo = taskwarrior_to_caldav(task)
    todo.last_modified = datetime(2026, 1, 2, 9, 0, 0, tzinfo=UTC)
    task.caldav_base = encode_base(snapshot_from_task(task))
    return task, todo


class TestThreeWayMerge:
    """Tests for classifying and syncing with a recorded base."""

    def test_no_base_and_equal_records_base(self, sync_engine) -> None:
        """A synced pair without a base is skipped and its base recorded."""
        task, todo = _synced_pair()
        task.caldav_base = None

        pair = sync_engine.classifier.classify(task, todo)

        assert pair.action == SyncAction.SKIP
        assert pair.merged is not None
        assert decode_base(pair.merged.caldav_base) == snapshot_from_task(task)

    def test_with_base_and_unchanged_skips(self, sync_engine) -> None:
        """Nothing changed since the last sync: plain skip."""
        task, todo = _synced_pair()

        pair = sync_engine.classifier.classify(task, todo)

        assert pair.action == SyncAction.SKIP
        assert pair.merged is None

    def test_taskwarrior_change_updates_caldav(self, sync_engine) -> None:
        """A field changed in TaskWarrior is written to CalDAV."""
        task, todo = _synced_pair()
        task.priority = "H"

        pair = sync_engine.classifier.classify(task, todo)

        assert pair.action == SyncAction.UPDATE
        assert pair.direction == SyncDirection.TW_TO_CALDAV
        assert pair.write_caldav and not pair.write_tw

    def test_caldav_change_wins_over_newer_taskwarrior(self, sync_engine) -> None:
        """A CalDAV-only change wins even if TaskWarrior was touched later."""
        task, todo = _synced_pair()
        task.modified = datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)
        todo.due = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

        pair = sync_engine.classifier.classify(task, todo)

        assert pair.direction == SyncDirection.CALDAV_TO_TW
        assert pair.merged.due == datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

    def test_changes_on_both_sides_are_both_kept(self, sync_engine) -> None:
        """TaskWarrior's priority and CalDAV's due date both survive."""
        task, todo = _synced_pair()
        task.priority = "H"
        todo.due = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

        pair = sync_engine.classifier.classify(task, todo)

        assert pair.direction == SyncDirection.BOTH
        assert pair.write_caldav and pair.write_tw
        assert pair.merged.priority == "H"
        assert pair.merged.due == datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

    def test_conflict_logs_a_warning(self, sync_engine, caplog) -> None:
        """The same field changed on both sides is logged."""
        task, todo = _synced_pair()
        task.description = "TW title"
        todo.summary = "CD title"
        todo.last_modified = datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)

        with caplog.at_level("WARNING", logger="twcaldav"):
            pair = sync_engine.classifier.classify(task, todo)

        assert pair.merged.description == "CD title"
        assert "title" in caplog.text

    def test_same_change_on_both_sides_records_base(self, sync_engine) -> None:
        """Both sides already agree on a new value: only the base is stale."""
        task, todo = _synced_pair()
        task.description = todo.summary = "Pay rent now"

        pair = sync_engine.classifier.classify(task, todo)

        assert pair.action == SyncAction.SKIP
        assert decode_base(pair.merged.caldav_base)["title"] == "Pay rent now"

    def test_completed_without_timestamp_is_not_rewritten(self, sync_engine) -> None:
        """TaskWarrior's own end time doesn't make a base without one stale."""
        task, todo = _synced_pair()
        todo.status = "COMPLETED"
        task.caldav_base = encode_base(snapshot_from_todo(todo))
        task.status = "completed"
        task.end = datetime(2026, 1, 3, 9, 0, 0, tzinfo=UTC)

        pair = sync_engine.classifier.classify(task, todo)

        assert pair.action == SyncAction.SKIP
        assert pair.merged is None

    def test_denotated_note_is_removed_from_caldav(
        self, sync_engine, mock_caldav, mock_tw
    ) -> None:
        """Removing the note annotation in TaskWarrior deletes the CalDAV note."""
        task, todo = _synced_pair()
        task.annotations = None

        pair = sync_engine.classifier.classify(task, todo)
        sync_engine._execute_sync_action(pair)

        written = mock_caldav.update_todo.call_args.args[1]
        assert not written.description
        assert written.uid == "cd-123"

    def test_both_writes_each_side_once(
        self, sync_engine, mock_caldav, mock_tw
    ) -> None:
        """A merge with changes on both sides writes each side once."""
        task, todo = _synced_pair()
        task.priority = "H"
        todo.due = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

        pair = sync_engine.classifier.classify(task, todo)
        sync_engine._execute_sync_action(pair)

        mock_caldav.update_todo.assert_called_once()
        assert mock_caldav.update_todo.call_args.args[0] == "Work Tasks"
        mock_tw.import_tasks.assert_called_once()
        imported = mock_tw.import_tasks.call_args.args[0][0]
        assert decode_base(imported.caldav_base) == snapshot_from_task(imported)
        assert sync_engine.stats.caldav_updated == 1
        assert sync_engine.stats.tw_updated == 1

    def test_caldav_only_write_still_records_base(
        self, sync_engine, mock_caldav, mock_tw
    ) -> None:
        """Updating only CalDAV stores the new base without counting a TW update."""
        task, todo = _synced_pair()
        task.priority = "H"

        pair = sync_engine.classifier.classify(task, todo)
        sync_engine._execute_sync_action(pair)

        imported = mock_tw.import_tasks.call_args.args[0][0]
        assert decode_base(imported.caldav_base)["priority"] == "H"
        assert sync_engine.stats.tw_updated == 0
        assert sync_engine.stats.bases_recorded == 1

    def test_record_base_on_skip(self, sync_engine, mock_tw) -> None:
        """A skip that carries a merged task writes only the base."""
        task, todo = _synced_pair()
        task.caldav_base = None

        pair = sync_engine.classifier.classify(task, todo)
        sync_engine._execute_sync_action(pair)

        mock_tw.import_tasks.assert_called_once()
        assert sync_engine.stats.skipped == 1
        assert sync_engine.stats.bases_recorded == 1

    def test_dry_run_writes_nothing(self, sample_config, mock_tw, mock_caldav) -> None:
        """Merges and base records are only logged in dry-run mode."""
        engine = SyncEngine(sample_config, mock_tw, mock_caldav, dry_run=True)
        task, todo = _synced_pair()
        task.priority = "H"
        todo.due = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

        engine._execute_sync_action(engine.classifier.classify(task, todo))

        mock_caldav.update_todo.assert_not_called()
        mock_tw.import_tasks.assert_not_called()

    @pytest.mark.parametrize(
        "change",
        [
            lambda task, todo: setattr(task, "priority", "H"),
            lambda task, todo: setattr(todo, "summary", "Renamed"),
            lambda task, todo: setattr(task, "annotations", None),
            lambda task, todo: setattr(todo, "description", "New note"),
            lambda task, todo: (
                setattr(task, "tags", ["a"]),
                setattr(todo, "due", datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)),
            ),
            lambda task, todo: (
                setattr(todo, "status", "COMPLETED"),
                setattr(todo, "completed", datetime(2026, 1, 3, 9, 0, 0, tzinfo=UTC)),
            ),
        ],
    )
    def test_merge_reaches_a_fixed_point(self, sync_engine, change) -> None:
        """After the merge is written to both sides, the next sync skips."""
        task, todo = _synced_pair()
        change(task, todo)

        pair = sync_engine.classifier.classify(task, todo)
        new_task = pair.merged
        new_todo = todo
        if pair.write_caldav:
            new_todo = taskwarrior_to_caldav(
                new_task,
                existing_description=todo.description,
                keep_existing_note=False,
            )

        again = sync_engine.classifier.classify(new_task, new_todo)

        assert again.action == SyncAction.SKIP
        assert again.merged is None

    @patch("twcaldav.sync_engine.taskwarrior_to_caldav")
    def test_no_base_lww_to_caldav_records_base(
        self, mock_convert, sync_engine, mock_caldav, mock_tw
    ) -> None:
        """An old-style update from TaskWarrior records TaskWarrior as the base."""
        task, todo = _synced_pair(description="New title")
        task.caldav_base = None
        mock_convert.return_value = VTodo(uid="x", summary="New title")
        pair = TaskPair(task, todo, SyncAction.UPDATE, SyncDirection.TW_TO_CALDAV, "")

        sync_engine._execute_update(pair)

        imported = mock_tw.import_tasks.call_args.args[0][0]
        assert decode_base(imported.caldav_base) == snapshot_from_task(task)

    def test_no_base_lww_from_caldav_records_caldav_as_base(
        self, sync_engine, mock_tw
    ) -> None:
        """An old-style update from CalDAV records the CalDAV todo as the base."""
        task, todo = _synced_pair()
        task.caldav_base = None
        task.annotations = [{"entry": "20260101T100000Z", "description": "tw only"}]
        pair = TaskPair(task, todo, SyncAction.UPDATE, SyncDirection.CALDAV_TO_TW, "")

        sync_engine._execute_update(pair)

        imported = mock_tw.import_tasks.call_args.args[0][0]
        assert decode_base(imported.caldav_base) == snapshot_from_todo(todo)

    def test_create_from_caldav_records_base(self, sync_engine, mock_tw) -> None:
        """A task created from CalDAV starts with the todo as its base."""
        _, todo = _synced_pair()
        pair = TaskPair(None, todo, SyncAction.CREATE, SyncDirection.CALDAV_TO_TW, "")

        sync_engine._execute_create(pair)

        created = mock_tw.create_task.call_args.args[0]
        assert decode_base(created.caldav_base) == snapshot_from_todo(todo)

    def test_create_to_caldav_records_uid_and_base(
        self, sync_engine, mock_caldav, mock_tw
    ) -> None:
        """A todo created from TaskWarrior links the task and records the base."""
        task, _ = _synced_pair()
        task.caldav_uid = task.caldav_base = None
        pair = TaskPair(task, None, SyncAction.CREATE, SyncDirection.TW_TO_CALDAV, "")

        sync_engine._execute_create(pair)

        created = mock_caldav.create_todo.call_args.args[1]
        imported = mock_tw.import_tasks.call_args.args[0][0]
        assert imported.caldav_uid == created.uid
        assert decode_base(imported.caldav_base) == snapshot_from_task(task)
        assert task.caldav_uid is None


class TestTimezoneMigration:
    """Tests for healing times stored shifted by older versions."""

    TASHKENT = ZoneInfo("Asia/Tashkent")

    def test_shifted_due_is_corrected_from_caldav(self, sync_engine) -> None:
        """A Tashkent due stored as wall-time-UTC is fixed in TaskWarrior only."""
        task, todo = _synced_pair()
        todo.due = datetime(2025, 8, 15, 12, 30, 1, tzinfo=self.TASHKENT)
        # What older versions stored, and recorded as the base
        task.due = datetime(2025, 8, 15, 12, 30, 1, tzinfo=UTC)
        base = snapshot_from_task(task)
        task.caldav_base = encode_base(base)

        pair = sync_engine.classifier.classify(task, todo)

        assert pair.direction == SyncDirection.CALDAV_TO_TW
        assert not pair.write_caldav
        assert pair.merged.to_dict()["due"] == "20250815T073001Z"
        fixed = Task.from_dict(pair.merged.to_dict())
        assert sync_engine.classifier.classify(fixed, todo).action == SyncAction.SKIP

    def test_tw_is_newer_compares_instants(self, sync_engine) -> None:
        """10:00 UTC is later than 12:00 in Tashkent (07:00 UTC)."""
        task, todo = _synced_pair()
        task.modified = datetime(2026, 1, 5, 10, 0, 0, tzinfo=UTC)
        todo.last_modified = datetime(2026, 1, 5, 12, 0, 0, tzinfo=self.TASHKENT)

        assert sync_engine.classifier._tw_is_newer(task, todo)
