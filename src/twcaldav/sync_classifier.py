"""Task classification logic for synchronization."""

from dataclasses import replace

from twcaldav.caldav_client import VTodo
from twcaldav.config import Config
from twcaldav.logger import get_logger
from twcaldav.sync_comparator import TaskComparator
from twcaldav.sync_merge import (
    build_merged_task,
    decode_base,
    encode_base,
    merge_snapshots,
    snapshot_from_task,
    snapshot_from_todo,
    snapshots_differ,
)
from twcaldav.sync_types import SyncAction, SyncDirection, TaskPair
from twcaldav.taskwarrior import Task, to_utc


class SyncClassifier:
    """Classifies task pairs to determine sync actions."""

    def __init__(self, config: Config, comparator: TaskComparator) -> None:
        self.config = config
        self.comparator = comparator
        self.logger = get_logger()

    def classify(self, tw_task: Task | None, caldav_todo: VTodo | None) -> TaskPair:
        """Classify a task pair and determine sync action.

        When the task has a base from the last sync, the two sides are merged
        field by field against it (see sync_merge). Without one:
        1. First checks if content differs (fields comparison)
        2. If content is identical, skip update and record the base
        3. If content differs, use Last Write Wins (timestamp) for conflict resolution

        Args:
            tw_task: TaskWarrior task (or None if not exists).
            caldav_todo: CalDAV todo (or None if not exists).

        Returns:
            TaskPair with classified action.
        """
        # Both missing - should not happen
        if tw_task is None and caldav_todo is None:
            return TaskPair(
                tw_task=None,
                caldav_todo=None,
                action=SyncAction.SKIP,
                direction=None,
                reason="Both tasks missing",
            )

        # Only TaskWarrior task exists
        if tw_task and not caldav_todo:
            return self._handle_tw_only(tw_task)

        # Only CalDAV todo exists
        if caldav_todo and not tw_task:
            return self._handle_caldav_only(caldav_todo)

        # Both exist - check for modifications
        assert tw_task is not None and caldav_todo is not None
        return self._handle_both_exist(tw_task, caldav_todo)

    def _handle_tw_only(self, tw_task: Task) -> TaskPair:
        if tw_task.status == "deleted":
            return TaskPair(
                tw_task=tw_task,
                caldav_todo=None,
                action=SyncAction.SKIP,
                direction=None,
                reason="TaskWarrior task deleted, no CalDAV todo to remove",
            )

        # Check if TW task has caldav_uid - if so, CalDAV todo was deleted
        if tw_task.caldav_uid:
            if self.config.sync.delete_tasks:
                return TaskPair(
                    tw_task=tw_task,
                    caldav_todo=None,
                    action=SyncAction.DELETE,
                    direction=SyncDirection.CALDAV_TO_TW,
                    reason="CalDAV todo deleted externally",
                )
            return TaskPair(
                tw_task=tw_task,
                caldav_todo=None,
                action=SyncAction.SKIP,
                direction=None,
                reason="CalDAV todo deleted externally, but deletion disabled",
            )

        # New TaskWarrior task without caldav_uid
        return TaskPair(
            tw_task=tw_task,
            caldav_todo=None,
            action=SyncAction.CREATE,
            direction=SyncDirection.TW_TO_CALDAV,
            reason="New TaskWarrior task",
        )

    def _handle_caldav_only(self, caldav_todo: VTodo) -> TaskPair:
        if caldav_todo.status == "CANCELLED":
            return TaskPair(
                tw_task=None,
                caldav_todo=caldav_todo,
                action=SyncAction.SKIP,
                direction=None,
                reason="CalDAV todo cancelled, no TaskWarrior task to remove",
            )
        return TaskPair(
            tw_task=None,
            caldav_todo=caldav_todo,
            action=SyncAction.CREATE,
            direction=SyncDirection.CALDAV_TO_TW,
            reason="New CalDAV todo",
        )

    def _handle_both_exist(self, tw_task: Task, caldav_todo: VTodo) -> TaskPair:
        # Handle deletion
        if tw_task.status == "deleted" and caldav_todo.status != "CANCELLED":
            if self.config.sync.delete_tasks:
                return TaskPair(
                    tw_task=tw_task,
                    caldav_todo=caldav_todo,
                    action=SyncAction.DELETE,
                    direction=SyncDirection.TW_TO_CALDAV,
                    reason="TaskWarrior task deleted",
                )
            return TaskPair(
                tw_task=tw_task,
                caldav_todo=caldav_todo,
                action=SyncAction.UPDATE,
                direction=SyncDirection.TW_TO_CALDAV,
                reason="TaskWarrior task deleted, setting CalDAV to CANCELLED",
            )

        if caldav_todo.status == "CANCELLED" and tw_task.status != "deleted":
            if self.config.sync.delete_tasks:
                return TaskPair(
                    tw_task=tw_task,
                    caldav_todo=caldav_todo,
                    action=SyncAction.DELETE,
                    direction=SyncDirection.CALDAV_TO_TW,
                    reason="CalDAV todo cancelled",
                )
            return TaskPair(
                tw_task=tw_task,
                caldav_todo=caldav_todo,
                action=SyncAction.SKIP,
                direction=None,
                reason="CalDAV todo cancelled, but deletion disabled",
            )

        # Both deleted/cancelled - skip
        if tw_task.status == "deleted" and caldav_todo.status == "CANCELLED":
            return TaskPair(
                tw_task=tw_task,
                caldav_todo=caldav_todo,
                action=SyncAction.SKIP,
                direction=None,
                reason="Both deleted",
            )

        base = decode_base(tw_task.caldav_base)
        if base is not None:
            return self._merge(tw_task, caldav_todo, base)

        # No base yet (task synced by an older version): compare content, then
        # use timestamps for conflict resolution
        content_equal = self.comparator.tasks_content_equal(tw_task, caldav_todo)

        if content_equal:
            # Content is identical - no update needed regardless of timestamps
            # This prevents spurious updates due to TW's import behavior
            return TaskPair(
                tw_task=tw_task,
                caldav_todo=caldav_todo,
                action=SyncAction.SKIP,
                direction=None,
                reason="No changes (content identical)",
                merged=replace(
                    tw_task,
                    extra=dict(tw_task.extra),
                    caldav_base=encode_base(snapshot_from_task(tw_task)),
                ),
            )

        # Content differs - use Last Write Wins for conflict resolution
        self.logger.debug(
            f"Content differs between TW:{tw_task.uuid} and CD:{caldav_todo.uid}"
        )

        return self._resolve_conflict(tw_task, caldav_todo)

    def _merge(self, tw_task: Task, caldav_todo: VTodo, base: dict) -> TaskPair:
        """Classify a pair by merging both sides against their base.

        Args:
            tw_task: TaskWarrior task.
            caldav_todo: CalDAV todo.
            base: Snapshot recorded at the last sync.

        Returns:
            TaskPair with the merged task and which sides to write.
        """
        tw_snapshot = snapshot_from_task(tw_task)
        cd_snapshot = snapshot_from_todo(caldav_todo)
        tw_newer = self._tw_is_newer(tw_task, caldav_todo)
        merged, conflicts = merge_snapshots(base, tw_snapshot, cd_snapshot, tw_newer)

        if conflicts:
            winner = "TaskWarrior" if tw_newer else "CalDAV"
            self.logger.warning(
                f"Conflict on '{tw_task.description}': {', '.join(conflicts)} "
                f"changed on both sides, keeping the {winner} value"
            )

        write_tw = snapshots_differ(merged, tw_snapshot)
        write_caldav = snapshots_differ(merged, cd_snapshot)

        if not write_tw and not write_caldav:
            # A base without a completion time stays valid, like a side without
            # one, so TaskWarrior's own end time doesn't cause a rewrite
            return TaskPair(
                tw_task=tw_task,
                caldav_todo=caldav_todo,
                action=SyncAction.SKIP,
                direction=None,
                reason="No changes (content identical)",
                merged=(
                    None
                    if not snapshots_differ(merged, base)
                    else build_merged_task(tw_task, caldav_todo, merged)
                ),
            )

        if write_tw and write_caldav:
            direction = SyncDirection.BOTH
            reason = "Merged changes from both sides"
        elif write_caldav:
            direction = SyncDirection.TW_TO_CALDAV
            reason = "Changed in TaskWarrior"
        else:
            direction = SyncDirection.CALDAV_TO_TW
            reason = "Changed in CalDAV"
        if conflicts:
            reason += f" (conflict: {', '.join(conflicts)})"

        return TaskPair(
            tw_task=tw_task,
            caldav_todo=caldav_todo,
            action=SyncAction.UPDATE,
            direction=direction,
            reason=reason,
            merged=build_merged_task(tw_task, caldav_todo, merged),
            write_tw=write_tw,
            write_caldav=write_caldav,
        )

    @staticmethod
    def _tw_is_newer(tw_task: Task, caldav_todo: VTodo) -> bool:
        """Return whether TaskWarrior was modified after CalDAV.

        Ties and a missing TaskWarrior timestamp go to CalDAV, as in
        _resolve_conflict.

        Args:
            tw_task: TaskWarrior task.
            caldav_todo: CalDAV todo.

        Returns:
            True if TaskWarrior wins a conflict.
        """
        tw_modified = tw_task.modified or tw_task.entry
        caldav_modified = caldav_todo.last_modified or caldav_todo.created
        if caldav_modified is None:
            return True
        if tw_modified is None:
            return False
        return to_utc(tw_modified) > to_utc(caldav_modified)

    def _resolve_conflict(self, tw_task: Task, caldav_todo: VTodo) -> TaskPair:
        tw_modified = tw_task.modified or tw_task.entry
        caldav_modified = caldav_todo.last_modified or caldav_todo.created

        if tw_modified is None and caldav_modified is None:
            # No timestamps but content differs - prefer TaskWarrior
            return TaskPair(
                tw_task=tw_task,
                caldav_todo=caldav_todo,
                action=SyncAction.UPDATE,
                direction=SyncDirection.TW_TO_CALDAV,
                reason="Content differs, no timestamps (preferring TW)",
            )

        if tw_modified is None:
            # Only CalDAV has timestamp - update TaskWarrior
            return TaskPair(
                tw_task=tw_task,
                caldav_todo=caldav_todo,
                action=SyncAction.UPDATE,
                direction=SyncDirection.CALDAV_TO_TW,
                reason="Content differs, CalDAV more recent (TW has no timestamp)",
            )

        if caldav_modified is None:
            # Only TaskWarrior has timestamp - update CalDAV
            return TaskPair(
                tw_task=tw_task,
                caldav_todo=caldav_todo,
                action=SyncAction.UPDATE,
                direction=SyncDirection.TW_TO_CALDAV,
                reason="Content differs, TaskWarrior more recent (CD has no timestamp)",
            )

        # Both have timestamps - compare (Last Write Wins)
        # Compare as UTC instants
        tw_timestamp = to_utc(tw_modified)
        caldav_timestamp = to_utc(caldav_modified)

        # Log timestamp comparisons for debugging
        time_diff = abs((tw_timestamp - caldav_timestamp).total_seconds())
        self.logger.debug(
            f"Timestamp comparison - TW:{tw_timestamp.isoformat()} "
            f"CD:{caldav_timestamp.isoformat()} "
            f"diff:{time_diff}s"
        )

        if tw_timestamp > caldav_timestamp:
            return TaskPair(
                tw_task=tw_task,
                caldav_todo=caldav_todo,
                action=SyncAction.UPDATE,
                direction=SyncDirection.TW_TO_CALDAV,
                reason="Content differs, TaskWarrior more recent",
            )
        return TaskPair(
            tw_task=tw_task,
            caldav_todo=caldav_todo,
            action=SyncAction.UPDATE,
            direction=SyncDirection.CALDAV_TO_TW,
            reason="Content differs, CalDAV more recent",
        )
