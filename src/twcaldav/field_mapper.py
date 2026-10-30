"""Field mapping between TaskWarrior and CalDAV."""

from datetime import datetime
from uuid import uuid4

from twcaldav.caldav_client import VTodo
from twcaldav.taskwarrior import Task


ANNOTATION_MARKER = "--- TaskWarrior Annotations ---"


def _annotation_fingerprint(annotation: dict) -> str:
    """Create unique fingerprint for annotation deduplication.

    Combines timestamp (entry) and description to uniquely identify an annotation.

    Args:
        annotation: Annotation dict with 'entry' and 'description' keys.

    Returns:
        Fingerprint string in format "TIMESTAMP:DESCRIPTION".
    """
    entry = annotation.get("entry", "")
    description = annotation.get("description", "")
    return f"{entry}:{description}"


def _merge_annotations(
    existing_annotations: list[dict], new_annotations: list[dict]
) -> list[dict]:
    """Merge annotations, avoiding duplicates.

    Preserves all existing annotations and adds new annotations that don't
    already exist (based on fingerprint matching).

    Args:
        existing_annotations: Current TaskWarrior task annotations.
        new_annotations: New annotations from CalDAV.

    Returns:
        Combined list with no duplicates (existing preserved, new added).
    """
    # Create fingerprints of existing annotations
    existing_fingerprints = {
        _annotation_fingerprint(ann) for ann in existing_annotations
    }

    # Start with all existing annotations
    merged = list(existing_annotations)

    # Add new annotations that don't exist
    for ann in new_annotations:
        if _annotation_fingerprint(ann) not in existing_fingerprints:
            merged.append(ann)

    return merged


def taskwarrior_to_caldav(task: Task, existing_description: str | None = None) -> VTodo:
    """Convert TaskWarrior task to CalDAV VTodo.

    Args:
        task: TaskWarrior Task object.
        existing_description: DESCRIPTION of the CalDAV todo being updated
            (optional). Any free-text note in it is carried over so an update
            from TaskWarrior does not wipe notes written in a CalDAV client.

    Returns:
        CalDAV VTodo object.
    """
    # Use existing CalDAV UID from UDA if available, otherwise generate new one
    uid = task.caldav_uid or str(uuid4())

    # Map status
    # TaskWarrior: pending, completed, deleted, waiting, recurring
    # CalDAV: NEEDS-ACTION, COMPLETED, CANCELLED, IN-PROCESS
    status_map = {
        "pending": "NEEDS-ACTION",
        "completed": "COMPLETED",
        "deleted": "CANCELLED",
        "waiting": "NEEDS-ACTION",
        "recurring": "NEEDS-ACTION",
    }
    status = status_map.get(task.status, "NEEDS-ACTION")

    # Map priority
    # TaskWarrior: H (high), M (medium), L (low), or None
    # CalDAV: 1-9 where 1 is highest, 5 is medium, 9 is lowest
    priority = None
    if task.priority:
        priority_map = {"H": 1, "M": 5, "L": 9}
        priority = priority_map.get(task.priority, 5)

    # Format description: existing CalDAV note (if any) followed by annotations
    note, _ = _parse_description_for_annotations(existing_description)
    description = _compose_description(note, _format_description_with_annotations(task))

    # Map tags to categories (excluding project - project is managed by mapping config)
    categories = task.tags if task.tags else None

    return VTodo(
        uid=uid,
        summary=task.description,
        status=status,
        description=description,
        due=task.due,
        dtstart=task.scheduled,
        wait=task.wait,
        completed=task.end,
        priority=priority,
        categories=categories,
        created=task.entry,
        last_modified=task.modified,
    )


def caldav_to_taskwarrior(vtodo: VTodo, existing_task: Task | None = None) -> Task:
    """Convert CalDAV VTodo to TaskWarrior task.

    Args:
        vtodo: CalDAV VTodo object.
        existing_task: Existing TaskWarrior task to update (optional).
                      If provided, preserves entry timestamp and UUID.

    Returns:
        TaskWarrior Task object.
    """
    # Use existing TW UUID if updating, otherwise generate new
    tw_uuid = existing_task.uuid if existing_task else str(uuid4())

    # Map status
    # CalDAV: NEEDS-ACTION, COMPLETED, CANCELLED, IN-PROCESS
    # TaskWarrior: pending, completed, deleted
    status_map = {
        "NEEDS-ACTION": "pending",
        "COMPLETED": "completed",
        "CANCELLED": "deleted",
        "IN-PROCESS": "pending",
    }
    status = status_map.get(vtodo.status or "NEEDS-ACTION", "pending")

    # Map priority
    # CalDAV: 1-9 (1=highest, 5=medium, 9=lowest)
    # TaskWarrior: H, M, L
    priority = None
    if vtodo.priority is not None:
        if vtodo.priority <= 3:
            priority = "H"
        elif vtodo.priority <= 6:
            priority = "M"
        else:
            priority = "L"

    # The TaskWarrior description is always the CalDAV summary (the title).
    # The CalDAV DESCRIPTION holds a free-text note plus the annotation block;
    # only the annotations are imported, the note stays on the CalDAV side.
    description = vtodo.summary
    _, new_annotations = _parse_description_for_annotations(vtodo.description)

    # Merge annotations if existing_task provided (deduplication)
    if existing_task and existing_task.annotations:
        annotations = _merge_annotations(
            existing_annotations=existing_task.annotations,
            new_annotations=new_annotations or [],
        )
    else:
        annotations = new_annotations

    # Map categories to tags (project is not synced via categories)
    # Project is determined by the calendar mapping configuration
    tags = vtodo.categories if vtodo.categories else []

    # Preserve entry timestamp from existing task or use created
    entry = existing_task.entry if existing_task else (vtodo.created or datetime.now())

    return Task(
        uuid=tw_uuid,
        description=description,
        status=status,
        entry=entry,
        modified=vtodo.last_modified or datetime.now(),
        project=None,  # Project will be set by sync engine based on calendar mapping
        due=vtodo.due,
        scheduled=vtodo.dtstart,
        wait=vtodo.wait,
        end=vtodo.completed,
        priority=priority,
        tags=tags if tags else None,
        annotations=annotations if annotations else None,
        caldav_uid=vtodo.uid,
    )


def _compose_description(note: str, annotation_block: str | None) -> str | None:
    """Join a free-text note and an annotation block into a DESCRIPTION value.

    Args:
        note: Free-text note (may be empty).
        annotation_block: Output of _format_description_with_annotations.

    Returns:
        Combined string, or None if both parts are empty.
    """
    parts = [part for part in (note.strip(), annotation_block) if part]
    return "\n".join(parts) if parts else None


def extract_annotation_block(description: str | None) -> str:
    """Return only the annotation block of a CalDAV DESCRIPTION.

    Args:
        description: CalDAV DESCRIPTION field.

    Returns:
        The marker and everything after it, stripped; empty string if the
        description has no annotation block.
    """
    if not description or ANNOTATION_MARKER not in description:
        return ""
    return (ANNOTATION_MARKER + description.split(ANNOTATION_MARKER, 1)[1]).strip()


def _format_description_with_annotations(task: Task) -> str | None:
    """Format task annotations for CalDAV description field.

    Uses pipe-delimited format: TIMESTAMP|DESCRIPTION
    Where TIMESTAMP is TaskWarrior format (YYYYMMDDTHHMMSSµZ).

    Args:
        task: TaskWarrior Task object.

    Returns:
        Formatted description string, or None if no annotations.
    """
    if not task.annotations:
        return None

    lines = [ANNOTATION_MARKER]

    for annotation in task.annotations:
        entry = annotation.get("entry", "")
        desc = annotation.get("description", "")

        # Ensure entry is in TW format (YYYYMMDDTHHMMSSµZ)
        if isinstance(entry, datetime):
            entry = entry.strftime("%Y%m%dT%H%M%SZ")
        # If it's already in TW format, use as-is
        # Otherwise try to parse and convert
        elif isinstance(entry, str) and not ("T" in entry and len(entry) >= 16):
            try:
                dt = datetime.fromisoformat(entry)
                entry = dt.strftime("%Y%m%dT%H%M%SZ")
            except (ValueError, AttributeError):
                # Skip annotations without valid timestamp
                continue

        if entry and desc:
            lines.append(f"{entry}|{desc}")

    # If only the header, return None
    if len(lines) == 1:
        return None

    return "\n".join(lines)


def _parse_description_for_annotations(
    description: str | None,
) -> tuple[str, list[dict] | None]:
    """Parse CalDAV description to extract annotations.

    Parses pipe-delimited format: TIMESTAMP|DESCRIPTION
    Where TIMESTAMP is TaskWarrior format (YYYYMMDDTHHMMSSµZ).

    Args:
        description: CalDAV description field.

    Returns:
        Tuple of (user_description, annotations_list).
        User description is empty string if only annotations exist.
        Annotations list is None if no annotations found.
    """
    from twcaldav.logger import get_logger

    logger = get_logger()

    if not description:
        return "", None

    # Check for annotation marker
    marker = ANNOTATION_MARKER
    if marker not in description:
        # No annotations, return as-is
        return description, None

    # Split on marker
    parts = description.split(marker)
    user_desc = parts[0].strip()

    # Parse annotations
    annotations = []
    if len(parts) > 1:
        annotation_text = parts[1].strip()
        for line in annotation_text.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Parse format: TIMESTAMP|DESCRIPTION
            if "|" in line:
                # Split on first pipe only (description may contain pipes)
                timestamp, desc = line.split("|", 1)
                timestamp = timestamp.strip()
                desc = desc.strip()

                # Validate timestamp format
                if "T" in timestamp and 15 <= len(timestamp) <= 17:
                    annotations.append({"entry": timestamp, "description": desc})
                else:
                    logger.warning(
                        f"Skipping annotation with invalid timestamp: {timestamp}"
                    )
            else:
                # Malformed line (no pipe delimiter)
                logger.warning(f"Skipping malformed annotation line: {line}")

    return user_desc, annotations if annotations else None
