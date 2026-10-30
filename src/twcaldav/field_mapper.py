"""Field mapping between TaskWarrior and CalDAV."""

import re
from datetime import datetime, timedelta
from uuid import uuid4

from twcaldav.caldav_client import VTodo
from twcaldav.taskwarrior import Task


ANNOTATION_HEADER = "Taskwarrior annotations:"
# Header of the pipe-delimited format written by twcaldav <= 1.2.0; still read.
LEGACY_ANNOTATION_MARKER = "--- TaskWarrior Annotations ---"
TW_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
DISPLAY_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S UTC"
CONTINUATION_INDENT = "  "

# A header only counts on a line of its own
_BLOCK_HEADER_RE = re.compile(
    rf"^[ \t]*({re.escape(ANNOTATION_HEADER)}|{re.escape(LEGACY_ANNOTATION_MARKER)})"
    r"[ \t]*$",
    re.MULTILINE,
)
_ANNOTATION_LINE_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC\] ?(.*)$"
)

# The CalDAV note is stored as the annotation dated this long before the task's
# entry. Real annotations are never older than their task, so they cannot
# collide with it.
NOTE_ENTRY_OFFSET = timedelta(seconds=1)


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

    # Format description: note followed by annotations. The note comes from
    # the TW note annotation; without one, keep the note already on CalDAV so
    # tasks synced before notes were imported do not lose it.
    note, _ = split_note_annotation(task)
    if not note:
        note = extract_note(existing_description)
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

    # Preserve entry timestamp from existing task or use created
    entry = existing_task.entry if existing_task else (vtodo.created or datetime.now())

    # The TaskWarrior description is always the CalDAV summary (the title).
    # The CalDAV DESCRIPTION holds a free-text note plus the annotation block;
    # the note becomes the note annotation, the block becomes annotations.
    description = vtodo.summary
    note, new_annotations = _parse_description_for_annotations(vtodo.description)
    note_ts = note_entry(entry)

    # The note annotation is owned by CalDAV: drop it from both sides and
    # re-add it from the current note, so edits replace and deletions remove it.
    new_annotations = [
        ann for ann in new_annotations or [] if _entry_str(ann) != note_ts
    ]
    existing_annotations = [
        ann
        for ann in (existing_task.annotations if existing_task else None) or []
        if _entry_str(ann) != note_ts
    ]

    # Merge annotations if existing_task provided (deduplication)
    if existing_annotations:
        annotations = _merge_annotations(
            existing_annotations=existing_annotations,
            new_annotations=new_annotations,
        )
    else:
        annotations = new_annotations

    note = _normalize_note(note)
    if note:
        annotations.append({"entry": note_ts, "description": note})

    # Map categories to tags (project is not synced via categories)
    # Project is determined by the calendar mapping configuration
    tags = vtodo.categories if vtodo.categories else []

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
        extra=dict(existing_task.extra) if existing_task else {},
    )


def note_entry(entry: datetime) -> str:
    """Return the annotation timestamp used for the CalDAV note.

    Formatted like Task.to_dict formats entry, so both stay consistent.

    Args:
        entry: The task's entry timestamp.

    Returns:
        TaskWarrior timestamp string one NOTE_ENTRY_OFFSET before entry.
    """
    return (entry - NOTE_ENTRY_OFFSET).strftime(TW_TIMESTAMP_FORMAT)


def _entry_str(annotation: dict) -> str:
    """Return an annotation's entry as a TaskWarrior timestamp string.

    Args:
        annotation: Annotation dict with an 'entry' key.

    Returns:
        Entry formatted as TW_TIMESTAMP_FORMAT, or the raw string value.
    """
    entry = annotation.get("entry", "")
    if isinstance(entry, datetime):
        return entry.strftime(TW_TIMESTAMP_FORMAT)
    return str(entry)


def _normalize_note(text: str | None) -> str:
    """Normalize a note for storage and comparison.

    Args:
        text: Note text (may be None).

    Returns:
        Text with LF line endings and surrounding whitespace removed.
    """
    if not text:
        return ""
    return text.replace("\r\n", "\n").strip()


def split_note_annotation(task: Task) -> tuple[str, list[dict]]:
    """Separate the CalDAV note annotation from the task's other annotations.

    Args:
        task: TaskWarrior Task object.

    Returns:
        Tuple of (normalized note text or "", remaining annotations).
    """
    note_ts = note_entry(task.entry)
    note = ""
    others = []
    for annotation in task.annotations or []:
        if _entry_str(annotation) == note_ts:
            note = _normalize_note(annotation.get("description"))
        else:
            others.append(annotation)
    return note, others


def extract_note(description: str | None) -> str:
    """Return the free-text note of a CalDAV DESCRIPTION.

    Args:
        description: CalDAV DESCRIPTION field.

    Returns:
        Normalized text before the annotation block, or "" if there is none.
    """
    note, _, _ = _split_description(description)
    return note


def parse_annotations(description: str | None) -> list[dict]:
    """Return the annotations stored in a CalDAV DESCRIPTION.

    Args:
        description: CalDAV DESCRIPTION field.

    Returns:
        Annotation dicts with TW-format 'entry' and 'description' keys.
    """
    _, annotations = _parse_description_for_annotations(description)
    return annotations or []


def _split_description(description: str | None) -> tuple[str, str, bool]:
    """Split a CalDAV DESCRIPTION into note and annotation block.

    Args:
        description: CalDAV DESCRIPTION field.

    Returns:
        Tuple of (normalized note, block text after the header, whether the
        block uses the legacy pipe format). The block is "" if there is none.
    """
    if not description:
        return "", "", False
    text = description.replace("\r\n", "\n")
    match = _BLOCK_HEADER_RE.search(text)
    if not match:
        return _normalize_note(text), "", False
    legacy = match.group(1) == LEGACY_ANNOTATION_MARKER
    return _normalize_note(text[: match.start()]), text[match.end() :], legacy


def _compose_description(note: str, annotation_block: str | None) -> str | None:
    """Join a free-text note and an annotation block into a DESCRIPTION value.

    Args:
        note: Free-text note (may be empty).
        annotation_block: Output of _format_description_with_annotations.

    Returns:
        Combined string, or None if both parts are empty.
    """
    parts = [part for part in (note.strip(), annotation_block) if part]
    return "\n\n".join(parts) if parts else None


def _format_description_with_annotations(task: Task) -> str | None:
    """Format task annotations for CalDAV description field.

    Writes a readable block, one annotation per line:

        Taskwarrior annotations:
        [2026-01-02 09:00:00 UTC] text
          continuation line of a multi-line annotation

    The note annotation is excluded; it is written as the plain note instead.

    Args:
        task: TaskWarrior Task object.

    Returns:
        Formatted description string, or None if no annotations.
    """
    _, annotations = split_note_annotation(task)
    if not annotations:
        return None

    lines = [ANNOTATION_HEADER]

    for annotation in annotations:
        entry = annotation.get("entry", "")
        desc = annotation.get("description", "")

        try:
            if isinstance(entry, datetime):
                timestamp = entry
            elif isinstance(entry, str) and "T" in entry and len(entry) >= 16:
                timestamp = datetime.strptime(entry[:15] + "Z", TW_TIMESTAMP_FORMAT)
            else:
                timestamp = datetime.fromisoformat(entry)
        except (ValueError, TypeError):
            # Skip annotations without valid timestamp
            continue

        if not desc:
            continue

        first, *rest = desc.replace("\r\n", "\n").split("\n")
        lines.append(f"[{timestamp.strftime(DISPLAY_TIMESTAMP_FORMAT)}] {first}")
        lines.extend(f"{CONTINUATION_INDENT}{line}" if line else "" for line in rest)

    # If only the header, return None
    if len(lines) == 1:
        return None

    return "\n".join(lines)


def _parse_description_for_annotations(
    description: str | None,
) -> tuple[str, list[dict] | None]:
    """Parse CalDAV description to extract annotations.

    Reads the readable format written by _format_description_with_annotations
    and the legacy pipe-delimited format (TIMESTAMP|DESCRIPTION).

    Args:
        description: CalDAV description field.

    Returns:
        Tuple of (user_description, annotations_list).
        User description is empty string if only annotations exist.
        Annotations list is None if no annotations found.
    """
    note, block, legacy = _split_description(description)
    if not block.strip():
        return note, None

    if legacy:
        annotations = _parse_legacy_block(block)
    else:
        annotations = _parse_readable_block(block)

    return note, annotations if annotations else None


def _parse_readable_block(block: str) -> list[dict]:
    """Parse the readable annotation block.

    Any line that is not a timestamp line continues the previous annotation,
    so the block survives clients that strip the indentation.

    Args:
        block: Text after the annotation header.

    Returns:
        Annotation dicts with TW-format 'entry' and 'description' keys.
    """
    from twcaldav.logger import get_logger

    logger = get_logger()

    annotations: list[dict] = []
    for line in block.split("\n"):
        match = _ANNOTATION_LINE_RE.match(line.strip())
        if match:
            timestamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            annotations.append(
                {
                    "entry": timestamp.strftime(TW_TIMESTAMP_FORMAT),
                    "description": match.group(2),
                }
            )
        elif annotations:
            if line.startswith(CONTINUATION_INDENT):
                line = line[len(CONTINUATION_INDENT) :]
            annotations[-1]["description"] += "\n" + line
        elif line.strip():
            logger.warning(f"Skipping malformed annotation line: {line}")

    for annotation in annotations:
        annotation["description"] = annotation["description"].rstrip()
    return annotations


def _parse_legacy_block(block: str) -> list[dict]:
    """Parse the legacy pipe-delimited annotation block (TIMESTAMP|DESCRIPTION).

    Args:
        block: Text after the legacy marker.

    Returns:
        Annotation dicts with TW-format 'entry' and 'description' keys.
    """
    from twcaldav.logger import get_logger

    logger = get_logger()

    annotations = []
    for line in block.split("\n"):
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

    return annotations
