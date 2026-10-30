"""Three-way merge of TaskWarrior tasks and CalDAV todos.

A snapshot is the comparable content of a task: the fields twcaldav syncs,
normalized so a task and the todo written from it give equal snapshots. After
every sync the agreed snapshot is stored on the TaskWarrior task (the
``caldav_base`` UDA). The next sync compares each side against that base, so a
field changed on one side wins even if the other side changed other fields,
and deletions (of notes, annotations, tags) are told apart from additions.
"""

import json
from dataclasses import replace
from datetime import datetime
from typing import Any

from twcaldav.caldav_client import VTodo
from twcaldav.field_mapper import (
    _entry_str,
    _normalize_note,
    caldav_priority_to_tw,
    caldav_to_taskwarrior,
    extract_note,
    note_entry,
    parse_annotations,
    split_note_annotation,
)
from twcaldav.taskwarrior import Task

BASE_VERSION = 1

# TaskWarrior status -> CalDAV STATUS, as taskwarrior_to_caldav maps it
_TW_TO_CALDAV_STATUS = {
    "pending": "NEEDS-ACTION",
    "completed": "COMPLETED",
    "deleted": "CANCELLED",
    "waiting": "NEEDS-ACTION",
    "recurring": "NEEDS-ACTION",
}

# CalDAV STATUS values TaskWarrior can't represent are compared as what they
# become in TaskWarrior, so IN-PROCESS isn't rewritten as a change.
_CALDAV_STATUS_CANONICAL = {"IN-PROCESS": "NEEDS-ACTION"}

SCALAR_FIELDS = (
    "title",
    "status",
    "end",
    "due",
    "scheduled",
    "wait",
    "priority",
    "note",
)
SET_FIELDS = ("tags", "annotations")

Snapshot = dict[str, Any]


def _timestamp(value: datetime | None) -> str | None:
    """Return a datetime as a comparable string.

    The timezone is dropped, not converted, matching TaskComparator.

    Args:
        value: Datetime or None.

    Returns:
        Naive ISO 8601 string, or None.
    """
    if value is None:
        return None
    return value.replace(tzinfo=None).isoformat()


def _snapshot(
    title: str,
    status: str,
    end: datetime | None,
    due: datetime | None,
    scheduled: datetime | None,
    wait: datetime | None,
    priority: str | None,
    tags: list[str] | None,
    note: str,
    annotations: list[dict],
) -> Snapshot:
    """Build a snapshot from already mapped values.

    Args:
        title: Task description / todo SUMMARY.
        status: CalDAV STATUS.
        end: Completion time.
        due: Due time.
        scheduled: Scheduled / DTSTART time.
        wait: Wait time.
        priority: TaskWarrior priority letter.
        tags: Tags / categories.
        note: Normalized note text.
        annotations: Annotations other than the note.

    Returns:
        The snapshot.
    """
    return {
        "title": title,
        "status": status,
        "end": _timestamp(end) if status == "COMPLETED" else None,
        "due": _timestamp(due),
        "scheduled": _timestamp(scheduled),
        "wait": _timestamp(wait),
        "priority": priority,
        "tags": sorted(set(tags or [])),
        "note": note,
        "annotations": sorted(
            [_entry_str(ann), _normalize_note(ann.get("description"))]
            for ann in annotations
            if ann.get("description")
        ),
    }


def snapshot_from_task(task: Task) -> Snapshot:
    """Return the snapshot of a TaskWarrior task.

    Args:
        task: TaskWarrior task.

    Returns:
        The task's snapshot.
    """
    note, annotations = split_note_annotation(task)
    return _snapshot(
        title=task.description,
        status=_TW_TO_CALDAV_STATUS.get(task.status, "NEEDS-ACTION"),
        end=task.end,
        due=task.due,
        scheduled=task.scheduled,
        wait=task.wait,
        priority=task.priority,
        tags=task.tags,
        note=note,
        annotations=annotations,
    )


def snapshot_from_todo(todo: VTodo) -> Snapshot:
    """Return the snapshot of a CalDAV todo.

    Args:
        todo: CalDAV todo.

    Returns:
        The todo's snapshot.
    """
    status = todo.status or "NEEDS-ACTION"
    return _snapshot(
        title=todo.summary,
        status=_CALDAV_STATUS_CANONICAL.get(status, status),
        end=todo.completed,
        due=todo.due,
        scheduled=todo.dtstart,
        wait=todo.wait,
        priority=caldav_priority_to_tw(todo.priority),
        tags=todo.categories,
        note=extract_note(todo.description),
        annotations=parse_annotations(todo.description),
    )


def encode_base(snapshot: Snapshot) -> str:
    """Serialize a snapshot for the caldav_base UDA.

    Args:
        snapshot: Snapshot to store.

    Returns:
        JSON string.
    """
    return json.dumps({"v": BASE_VERSION, **snapshot}, sort_keys=True)


def decode_base(text: str | None) -> Snapshot | None:
    """Read a snapshot stored in the caldav_base UDA.

    Args:
        text: UDA value, or None.

    Returns:
        The snapshot, or None if there is none or it can't be used.
    """
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.pop("v", None) != BASE_VERSION:
        return None
    if set(data) != set(SCALAR_FIELDS) | set(SET_FIELDS):
        return None
    return data


def _merge_scalar(base: Any, tw: Any, cd: Any, tw_newer: bool) -> tuple[Any, bool]:
    """Merge one field.

    Args:
        base: Value at the last sync.
        tw: TaskWarrior value.
        cd: CalDAV value.
        tw_newer: Whether TaskWarrior was modified more recently.

    Returns:
        Tuple of (merged value, whether it was a conflict).
    """
    if tw == cd:
        return tw, False
    if tw == base:
        return cd, False
    if cd == base:
        return tw, False
    return (tw if tw_newer else cd), True


def _merge_set(base: list, tw: list, cd: list) -> list:
    """Merge a set-valued field: keep additions, apply removals from both sides.

    Args:
        base: Items at the last sync.
        tw: TaskWarrior items.
        cd: CalDAV items.

    Returns:
        Sorted merged items.
    """
    as_set = lambda items: {tuple(i) if isinstance(i, list) else i for i in items}  # noqa: E731
    base_set, tw_set, cd_set = as_set(base), as_set(tw), as_set(cd)
    removed = (base_set - tw_set) | (base_set - cd_set)
    merged = (tw_set | cd_set) - removed
    return sorted(list(i) if isinstance(i, tuple) else i for i in merged)


def merge_snapshots(
    base: Snapshot, tw: Snapshot, cd: Snapshot, tw_newer: bool
) -> tuple[Snapshot, list[str]]:
    """Merge TaskWarrior and CalDAV snapshots against their common base.

    A field changed on one side takes that side's value. A field changed on
    both sides to different values is a conflict, and the side modified more
    recently wins it. Tags and annotations are merged as sets. A missing
    completion time means "unknown", not "cleared".

    Args:
        base: Snapshot stored at the last sync.
        tw: Current TaskWarrior snapshot.
        cd: Current CalDAV snapshot.
        tw_newer: Whether TaskWarrior was modified more recently.

    Returns:
        Tuple of (merged snapshot, names of conflicting fields).
    """
    merged: Snapshot = {}
    conflicts: list[str] = []
    for field in SCALAR_FIELDS:
        tw_value, cd_value = tw[field], cd[field]
        if field == "end" and (tw_value is None or cd_value is None):
            merged[field] = tw_value if cd_value is None else cd_value
            continue
        merged[field], conflict = _merge_scalar(
            base[field], tw_value, cd_value, tw_newer
        )
        if conflict:
            conflicts.append(field)
    for field in SET_FIELDS:
        merged[field] = _merge_set(base[field], tw[field], cd[field])
    if merged["status"] != "COMPLETED":
        merged["end"] = None
    return merged, conflicts


def snapshots_differ(merged: Snapshot, side: Snapshot) -> bool:
    """Return whether a side has to be written to match the merge.

    A side without a completion time is not rewritten just to add one.

    Args:
        merged: Merged snapshot.
        side: Snapshot of one side.

    Returns:
        True if the side differs from the merge.
    """
    return any(
        merged[field] != side[field] and not (field == "end" and side[field] is None)
        for field in merged
    )


def build_merged_task(tw_task: Task, todo: VTodo, merged: Snapshot) -> Task:
    """Build the TaskWarrior task for a merged snapshot.

    Fields where the merge differs from the task take the CalDAV value, so no
    value is re-parsed from the snapshot. Everything else, including fields
    twcaldav doesn't sync, stays as it is. The merge is stored as the new base.

    Args:
        tw_task: Current TaskWarrior task.
        todo: Current CalDAV todo.
        merged: Merged snapshot.

    Returns:
        A new Task; tw_task is not modified.
    """
    current = snapshot_from_task(tw_task)
    from_caldav = caldav_to_taskwarrior(todo, existing_task=tw_task)
    result = replace(tw_task, extra=dict(tw_task.extra))

    changed = {field for field in merged if merged[field] != current[field]}
    if "title" in changed:
        result.description = from_caldav.description
    if "status" in changed:
        result.status = from_caldav.status
    if "end" in changed:
        result.end = from_caldav.end if merged["end"] is not None else None
    for field, attr in (
        ("due", "due"),
        ("scheduled", "scheduled"),
        ("wait", "wait"),
        ("priority", "priority"),
    ):
        if field in changed:
            setattr(result, attr, getattr(from_caldav, attr))

    if "tags" in changed:
        kept = [tag for tag in tw_task.tags or [] if tag in merged["tags"]]
        result.tags = kept + [tag for tag in merged["tags"] if tag not in kept] or None

    if "note" in changed or "annotations" in changed:
        _, others = split_note_annotation(tw_task)
        wanted = {tuple(item) for item in merged["annotations"]}
        annotations = []
        for ann in others:
            key = (_entry_str(ann), _normalize_note(ann.get("description")))
            # Keep empty annotations, which aren't synced, and merged ones
            if not ann.get("description") or key in wanted:
                annotations.append(ann)
                wanted.discard(key)
        annotations += [
            {"entry": entry, "description": text} for entry, text in sorted(wanted)
        ]
        if merged["note"]:
            annotations.append(
                {"entry": note_entry(tw_task.entry), "description": merged["note"]}
            )
        result.annotations = annotations or None

    result.caldav_base = encode_base(merged)
    return result
