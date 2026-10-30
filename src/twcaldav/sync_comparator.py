"""Task comparison logic for synchronization."""

from datetime import datetime

from twcaldav.caldav_client import VTodo
from twcaldav.logger import get_logger
from twcaldav.taskwarrior import Task, to_utc


def _instant(value: datetime | None) -> datetime | None:
    """Return a datetime as a naive UTC instant for comparison.

    Args:
        value: Datetime or None.

    Returns:
        Naive datetime in UTC, or None.
    """
    return to_utc(value).replace(tzinfo=None) if value else None


class TaskComparator:
    """Compares TaskWarrior tasks and CalDAV todos to detect changes."""

    def __init__(self) -> None:
        self.logger = get_logger()

    def tasks_content_equal(self, tw_task: Task, caldav_todo: VTodo) -> bool:
        """Compare task content (not timestamps) to detect real changes.

        Args:
            tw_task: TaskWarrior task.
            caldav_todo: CalDAV todo.

        Returns:
            True if content is identical, False if any field differs.
        """
        # Compare description/summary
        if tw_task.description != caldav_todo.summary:
            self.logger.debug(
                f"Content differs: description/summary - "
                f"TW:'{tw_task.description}' vs CD:'{caldav_todo.summary}'"
            )
            return False

        # Compare status
        status_map = {
            "pending": "NEEDS-ACTION",
            "completed": "COMPLETED",
            "deleted": "CANCELLED",
            "waiting": "NEEDS-ACTION",
            "recurring": "NEEDS-ACTION",
        }
        expected_caldav_status = status_map.get(tw_task.status, "NEEDS-ACTION")
        actual_caldav_status = caldav_todo.status or "NEEDS-ACTION"
        if expected_caldav_status != actual_caldav_status:
            self.logger.debug(
                f"Content differs: status - "
                f"TW:'{tw_task.status}' ({expected_caldav_status}) vs "
                f"CD:{actual_caldav_status}"
            )
            return False

        # Compare due date (as UTC instants)
        tw_due = _instant(tw_task.due)
        cd_due = _instant(caldav_todo.due)
        if tw_due != cd_due:
            self.logger.debug(f"Content differs: due - TW:{tw_due} vs CD:{cd_due}")
            return False

        # Compare scheduled/dtstart (as UTC instants)
        tw_scheduled = _instant(tw_task.scheduled)
        cd_dtstart = _instant(caldav_todo.dtstart)
        if tw_scheduled != cd_dtstart:
            self.logger.debug(
                f"Content differs: scheduled/dtstart - "
                f"TW:{tw_scheduled} vs CD:{cd_dtstart}"
            )
            return False

        # Compare wait (as UTC instants)
        tw_wait = _instant(tw_task.wait)
        cd_wait = _instant(caldav_todo.wait)
        if tw_wait != cd_wait:
            self.logger.debug(f"Content differs: wait - TW:{tw_wait} vs CD:{cd_wait}")
            return False

        # Compare end/completed timestamp (as UTC instants)
        # Only compare if both tasks are completed status
        if tw_task.status == "completed" and caldav_todo.status == "COMPLETED":
            tw_end = _instant(tw_task.end)
            cd_completed = _instant(caldav_todo.completed)
            # Only consider it a difference if BOTH have completion timestamps
            # If CalDAV lacks the COMPLETED timestamp, the status already indicates
            # completion, so don't treat this as a content difference
            if tw_end is not None and cd_completed is not None:
                if tw_end != cd_completed:
                    self.logger.debug(
                        f"Content differs: end/completed - "
                        f"TW:{tw_end} vs CD:{cd_completed}"
                    )
                    return False
            # If only one side has the timestamp, log but don't treat as difference
            elif tw_end != cd_completed:
                self.logger.debug(
                    f"Ignoring end/completed mismatch (missing timestamp): "
                    f"TW:{tw_end} vs CD:{cd_completed}"
                )

        # Compare priority
        priority_map = {"H": 1, "M": 5, "L": 9}
        expected_caldav_priority = (
            priority_map.get(tw_task.priority) if tw_task.priority else None
        )
        if expected_caldav_priority != caldav_todo.priority:
            self.logger.debug(
                f"Content differs: priority - "
                f"TW:{tw_task.priority} ({expected_caldav_priority}) vs "
                f"CD:{caldav_todo.priority}"
            )
            return False

        # Compare tags/categories
        tw_tags = set(tw_task.tags or [])
        cd_categories = set(caldav_todo.categories or [])
        if tw_tags != cd_categories:
            self.logger.debug(
                f"Content differs: tags/categories - TW:{tw_tags} vs CD:{cd_categories}"
            )
            return False

        # Compare annotations (stored in CalDAV description) by timestamp and
        # text, so the block format (readable or legacy) does not matter. The
        # note annotation is compared against the CalDAV note below.
        from twcaldav.field_mapper import (
            _entry_str,
            _normalize_note,
            extract_note,
            parse_annotations,
            split_note_annotation,
        )

        tw_note, tw_annotations = split_note_annotation(tw_task)
        expected_annotations = sorted(
            (_entry_str(ann), _normalize_note(ann.get("description")))
            for ann in tw_annotations
            if ann.get("description")
        )
        actual_annotations = sorted(
            (_entry_str(ann), _normalize_note(ann.get("description")))
            for ann in parse_annotations(caldav_todo.description)
        )

        if expected_annotations != actual_annotations:
            self.logger.debug(
                f"Content differs: annotations - "
                f"TW has {len(expected_annotations)} vs "
                f"CD has {len(actual_annotations)}"
            )
            return False

        # Compare the CalDAV note against the TW note annotation
        cd_note = extract_note(caldav_todo.description)
        if tw_note != cd_note:
            self.logger.debug(
                f"Content differs: note - "
                f"TW has {len(tw_note)} chars vs CD has {len(cd_note)} chars"
            )
            return False

        return True
