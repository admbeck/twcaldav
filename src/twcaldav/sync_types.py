"""Shared types for synchronization logic."""

from dataclasses import dataclass
from enum import Enum

from twcaldav.caldav_client import VTodo
from twcaldav.taskwarrior import Task


class SyncAction(Enum):
    """Represents possible sync actions."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SKIP = "skip"


class SyncDirection(Enum):
    """Represents sync direction."""

    TW_TO_CALDAV = "tw_to_caldav"
    CALDAV_TO_TW = "caldav_to_tw"
    BOTH = "both"


@dataclass
class TaskPair:
    """Represents a pair of related tasks from TaskWarrior and CalDAV."""

    tw_task: Task | None
    caldav_todo: VTodo | None
    action: SyncAction
    direction: SyncDirection | None
    reason: str
    # Set by the three-way merge: the TaskWarrior task to write, carrying the
    # new base. On a SKIP it means only the base needs recording.
    merged: Task | None = None
    write_tw: bool = False
    write_caldav: bool = False


@dataclass
class SyncStats:
    """Statistics for a sync operation."""

    tw_created: int = 0
    tw_updated: int = 0
    tw_deleted: int = 0
    caldav_created: int = 0
    caldav_updated: int = 0
    caldav_deleted: int = 0
    skipped: int = 0
    bases_recorded: int = 0
    errors: int = 0

    def __str__(self) -> str:
        """Format sync statistics for display."""
        lines = [
            "Sync Statistics:",
            (
                f"  TaskWarrior: {self.tw_created} created, "
                f"{self.tw_updated} updated, {self.tw_deleted} deleted"
            ),
            (
                f"  CalDAV: {self.caldav_created} created, "
                f"{self.caldav_updated} updated, {self.caldav_deleted} deleted"
            ),
            f"  Skipped: {self.skipped}",
            f"  Bases recorded: {self.bases_recorded}",
            f"  Errors: {self.errors}",
        ]
        return "\n".join(lines)
