"""Task comparison logic for synchronization."""

from twcaldav.caldav_client import VTodo
from twcaldav.logger import get_logger
from twcaldav.taskwarrior import Task


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

        # Compare due date (handle None and timezone differences)
        tw_due = tw_task.due.replace(tzinfo=None) if tw_task.due else None
        cd_due = caldav_todo.due.replace(tzinfo=None) if caldav_todo.due else None
        if tw_due != cd_due:
            self.logger.debug(f"Content differs: due - TW:{tw_due} vs CD:{cd_due}")
            return False

        # Compare scheduled/dtstart (handle None and timezone differences)
        tw_scheduled = (
            tw_task.scheduled.replace(tzinfo=None) if tw_task.scheduled else None
        )
        cd_dtstart = (
            caldav_todo.dtstart.replace(tzinfo=None) if caldav_todo.dtstart else None
        )
        if tw_scheduled != cd_dtstart:
            self.logger.debug(
                f"Content differs: scheduled/dtstart - "
                f"TW:{tw_scheduled} vs CD:{cd_dtstart}"
            )
            return False

        # Compare wait (handle None and timezone differences)
        tw_wait = tw_task.wait.replace(tzinfo=None) if tw_task.wait else None
        cd_wait = caldav_todo.wait.replace(tzinfo=None) if caldav_todo.wait else None
        if tw_wait != cd_wait:
            self.logger.debug(f"Content differs: wait - TW:{tw_wait} vs CD:{cd_wait}")
            return False

        # Compare end/completed timestamp (handle None and timezone differences)
        # Only compare if both tasks are completed status
        if tw_task.status == "completed" and caldav_todo.status == "COMPLETED":
            tw_end = tw_task.end.replace(tzinfo=None) if tw_task.end else None
            cd_completed = (
                caldav_todo.completed.replace(tzinfo=None)
                if caldav_todo.completed
                else None
            )
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

        # Compare annotations (stored in CalDAV description)
        from twcaldav.field_mapper import (
            _format_description_with_annotations,
            extract_annotation_block,
            extract_note,
            split_note_annotation,
        )

        expected_caldav_description = _format_description_with_annotations(tw_task)

        # The annotation block holds every annotation except the note
        # annotation, which is compared against the CalDAV note below.
        expected_desc = expected_caldav_description or ""
        actual_desc = extract_annotation_block(caldav_todo.description)

        if expected_desc != actual_desc:
            self.logger.debug(
                f"Content differs: annotations/description - "
                f"TW has {len(expected_desc)} chars vs CD has {len(actual_desc)} chars"
            )
            return False

        # Compare the CalDAV note against the TW note annotation
        tw_note, _ = split_note_annotation(tw_task)
        cd_note = extract_note(caldav_todo.description)
        if tw_note != cd_note:
            self.logger.debug(
                f"Content differs: note - "
                f"TW has {len(tw_note)} chars vs CD has {len(cd_note)} chars"
            )
            return False

        return True
