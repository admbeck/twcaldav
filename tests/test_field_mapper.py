"""Tests for field mapping module."""

from datetime import UTC, datetime

from twcaldav.caldav_client import VTodo
from twcaldav.field_mapper import (
    caldav_to_taskwarrior,
    taskwarrior_to_caldav,
)
from twcaldav.taskwarrior import Task


class TestTaskWarriorToCalDAV:
    """Tests for TaskWarrior to CalDAV conversion."""

    def test_minimal_conversion(self) -> None:
        """Test converting minimal task."""
        task = Task(
            uuid="12345678-1234-1234-1234-123456789012",
            description="Test task",
            status="pending",
            entry=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
        )

        vtodo = taskwarrior_to_caldav(task)

        # CalDAV UID should be generated (UUID4 format)
        assert len(vtodo.uid) == 36  # UUID4 format
        assert "-" in vtodo.uid
        assert vtodo.summary == "Test task"
        assert vtodo.status == "NEEDS-ACTION"

    def test_full_conversion(self) -> None:
        """Test converting complete task."""
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
        )

        vtodo = taskwarrior_to_caldav(task)

        assert vtodo.summary == "Complete task"
        assert vtodo.status == "NEEDS-ACTION"
        assert vtodo.due == datetime(2024, 11, 20, 12, 0, 0, tzinfo=UTC)
        assert vtodo.priority == 1  # H -> 1
        # Project is not synced to categories - only tags are synced
        assert vtodo.categories == ["important", "urgent"]

    def test_status_mapping(self) -> None:
        """Test status mapping."""
        # pending -> NEEDS-ACTION
        task = Task(
            uuid="test-uuid",
            description="Test",
            status="pending",
            entry=datetime.now(UTC),
        )
        vtodo = taskwarrior_to_caldav(task)
        assert vtodo.status == "NEEDS-ACTION"

        # completed -> COMPLETED
        task.status = "completed"
        vtodo = taskwarrior_to_caldav(task)
        assert vtodo.status == "COMPLETED"

        # deleted -> CANCELLED
        task.status = "deleted"
        vtodo = taskwarrior_to_caldav(task)
        assert vtodo.status == "CANCELLED"

    def test_priority_mapping(self) -> None:
        """Test priority mapping."""
        task = Task(
            uuid="test-uuid",
            description="Test",
            status="pending",
            entry=datetime.now(UTC),
        )

        # H -> 1
        task.priority = "H"
        vtodo = taskwarrior_to_caldav(task)
        assert vtodo.priority == 1

        # M -> 5
        task.priority = "M"
        vtodo = taskwarrior_to_caldav(task)
        assert vtodo.priority == 5

        # L -> 9
        task.priority = "L"
        vtodo = taskwarrior_to_caldav(task)
        assert vtodo.priority == 9

        # None -> None
        task.priority = None
        vtodo = taskwarrior_to_caldav(task)
        assert vtodo.priority is None

    def test_annotations_in_description(self) -> None:
        """Test annotations are formatted in description."""
        task = Task(
            uuid="test-uuid",
            description="Test",
            status="pending",
            entry=datetime.now(UTC),
            annotations=[
                {"entry": "20241117T103000Z", "description": "First note"},
                {"entry": "20241117T110000Z", "description": "Second note"},
            ],
        )

        vtodo = taskwarrior_to_caldav(task)

        assert vtodo.description == (
            "Taskwarrior annotations:\n"
            "[2024-11-17 10:30:00 UTC] First note\n"
            "[2024-11-17 11:00:00 UTC] Second note"
        )

    def test_categories_from_tags_only(self) -> None:
        """Test categories include only tags (not project)."""
        task = Task(
            uuid="test-uuid",
            description="Test",
            status="pending",
            entry=datetime.now(UTC),
            project="work",
            tags=["urgent", "important"],
        )

        vtodo = taskwarrior_to_caldav(task)

        # Project is not synced to categories - only tags
        assert vtodo.categories == ["urgent", "important"]

    def test_scheduled_to_dtstart(self) -> None:
        """Test scheduled field is mapped to DTSTART."""
        task = Task(
            uuid="test-uuid",
            description="Task with scheduled date",
            status="pending",
            entry=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
            scheduled=datetime(2024, 11, 20, 9, 0, 0, tzinfo=UTC),
        )

        vtodo = taskwarrior_to_caldav(task)

        assert vtodo.dtstart == datetime(2024, 11, 20, 9, 0, 0, tzinfo=UTC)

    def test_scheduled_none_maps_to_no_dtstart(self) -> None:
        """Test None scheduled does not set DTSTART."""
        task = Task(
            uuid="test-uuid",
            description="Task without scheduled",
            status="pending",
            entry=datetime.now(UTC),
            scheduled=None,
        )

        vtodo = taskwarrior_to_caldav(task)

        assert vtodo.dtstart is None

    def test_wait_to_x_taskwarrior_wait(self) -> None:
        """Test wait field is mapped to X-TASKWARRIOR-WAIT."""
        task = Task(
            uuid="test-uuid",
            description="Task with wait date",
            status="pending",
            entry=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
            wait=datetime(2024, 11, 25, 8, 0, 0, tzinfo=UTC),
        )

        vtodo = taskwarrior_to_caldav(task)

        assert vtodo.wait == datetime(2024, 11, 25, 8, 0, 0, tzinfo=UTC)

    def test_wait_none_maps_to_no_x_taskwarrior_wait(self) -> None:
        """Test None wait does not set X-TASKWARRIOR-WAIT."""
        task = Task(
            uuid="test-uuid",
            description="Task without wait",
            status="pending",
            entry=datetime.now(UTC),
            wait=None,
        )

        vtodo = taskwarrior_to_caldav(task)

        assert vtodo.wait is None

    def test_end_to_completed(self) -> None:
        """Test end field is mapped to COMPLETED timestamp."""
        task = Task(
            uuid="test-uuid",
            description="Completed task",
            status="completed",
            entry=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
            end=datetime(2024, 11, 21, 15, 30, 0, tzinfo=UTC),
        )

        vtodo = taskwarrior_to_caldav(task)

        assert vtodo.completed == datetime(2024, 11, 21, 15, 30, 0, tzinfo=UTC)
        assert vtodo.status == "COMPLETED"

    def test_end_none_maps_to_no_completed(self) -> None:
        """Test None end does not set COMPLETED timestamp."""
        task = Task(
            uuid="test-uuid",
            description="Pending task",
            status="pending",
            entry=datetime.now(UTC),
            end=None,
        )

        vtodo = taskwarrior_to_caldav(task)

        assert vtodo.completed is None
        assert vtodo.status == "NEEDS-ACTION"


class TestCalDAVToTaskWarrior:
    """Tests for CalDAV to TaskWarrior conversion."""

    def test_minimal_conversion(self) -> None:
        """Test converting minimal VTodo."""
        vtodo = VTodo(
            uid="caldav-uid-123",
            summary="Test task",
            created=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.description == "Test task"
        assert task.status == "pending"
        assert task.entry == datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC)

    def test_full_conversion(self) -> None:
        """Test converting complete VTodo."""
        vtodo = VTodo(
            uid="caldav-uid-123",
            summary="Complete task",
            status="NEEDS-ACTION",
            due=datetime(2024, 11, 20, 12, 0, 0, tzinfo=UTC),
            priority=1,
            categories=["work", "urgent"],
            created=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
            last_modified=datetime(2024, 11, 17, 11, 0, 0, tzinfo=UTC),
        )

        task = caldav_to_taskwarrior(vtodo)

        # TW UUID is generated, CalDAV UID stored in UDA
        assert len(task.uuid) == 36  # UUID4 format
        assert task.caldav_uid == "caldav-uid-123"
        assert task.description == "Complete task"
        assert task.status == "pending"
        # Project is not set from categories - it will be set by sync engine
        assert task.project is None
        assert task.tags == ["work", "urgent"]
        assert task.priority == "H"

    def test_update_keeps_unmapped_task_fields(self) -> None:
        """Fields CalDAV doesn't carry, like depends, survive an update."""
        existing = Task(
            uuid="tw-uuid",
            description="Task",
            status="pending",
            entry=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
            extra={"start": "20241117T103000Z", "depends": ["other-uuid"]},
        )
        vtodo = VTodo(uid="caldav-uid-123", summary="Renamed")

        task = caldav_to_taskwarrior(vtodo, existing_task=existing)

        assert task.extra == {"start": "20241117T103000Z", "depends": ["other-uuid"]}
        assert task.extra is not existing.extra

    def test_status_mapping(self) -> None:
        """Test status mapping."""
        vtodo = VTodo(uid="test-uid", summary="Test", created=datetime.now(UTC))

        # NEEDS-ACTION -> pending
        vtodo.status = "NEEDS-ACTION"
        task = caldav_to_taskwarrior(vtodo)
        assert task.status == "pending"

        # COMPLETED -> completed
        vtodo.status = "COMPLETED"
        task = caldav_to_taskwarrior(vtodo)
        assert task.status == "completed"

        # CANCELLED -> deleted
        vtodo.status = "CANCELLED"
        task = caldav_to_taskwarrior(vtodo)
        assert task.status == "deleted"

        # IN-PROCESS -> pending
        vtodo.status = "IN-PROCESS"
        task = caldav_to_taskwarrior(vtodo)
        assert task.status == "pending"

    def test_priority_mapping(self) -> None:
        """Test priority mapping."""
        vtodo = VTodo(uid="test-uid", summary="Test", created=datetime.now(UTC))

        # 1-3 -> H
        vtodo.priority = 1
        task = caldav_to_taskwarrior(vtodo)
        assert task.priority == "H"

        vtodo.priority = 3
        task = caldav_to_taskwarrior(vtodo)
        assert task.priority == "H"

        # 4-6 -> M
        vtodo.priority = 5
        task = caldav_to_taskwarrior(vtodo)
        assert task.priority == "M"

        # 7-9 -> L
        vtodo.priority = 9
        task = caldav_to_taskwarrior(vtodo)
        assert task.priority == "L"

        # None -> None
        vtodo.priority = None
        task = caldav_to_taskwarrior(vtodo)
        assert task.priority is None

    def test_annotations_from_description(self) -> None:
        """Test parsing annotations from description."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Test",
            description=(
                "--- TaskWarrior Annotations ---\n"
                "20241117T103000Z|First note\n"
                "20241117T110000Z|Second note"
            ),
            created=datetime.now(UTC),
        )

        task = caldav_to_taskwarrior(vtodo)

        # When description only contains annotations, use summary as description
        assert task.description == "Test"
        assert task.annotations is not None
        assert len(task.annotations) == 2
        assert task.annotations[0]["entry"] == "20241117T103000Z"
        assert task.annotations[0]["description"] == "First note"
        assert task.annotations[1]["entry"] == "20241117T110000Z"
        assert task.annotations[1]["description"] == "Second note"

    def test_preserve_existing_task_entry(self) -> None:
        """Test preserving entry timestamp from existing task."""
        original_entry = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        existing_task = Task(
            uuid="existing-uuid",
            description="Original",
            status="pending",
            entry=original_entry,
        )

        vtodo = VTodo(
            uid="test-uid",
            summary="Updated task",
            created=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
        )

        task = caldav_to_taskwarrior(vtodo, existing_task=existing_task)

        assert task.entry == original_entry
        assert task.uuid == "existing-uuid"

    def test_categories_to_tags_only(self) -> None:
        """Test categories are mapped to tags only (not project)."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Test",
            categories=["work", "urgent", "important"],
            created=datetime.now(UTC),
        )

        task = caldav_to_taskwarrior(vtodo)

        # Project is not set from categories - it will be set by sync engine
        assert task.project is None
        assert task.tags == ["work", "urgent", "important"]

    def test_dtstart_to_scheduled(self) -> None:
        """Test DTSTART is mapped to scheduled field."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Task with start date",
            created=datetime.now(UTC),
            dtstart=datetime(2024, 11, 20, 9, 0, 0, tzinfo=UTC),
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.scheduled == datetime(2024, 11, 20, 9, 0, 0, tzinfo=UTC)

    def test_dtstart_none_maps_to_no_scheduled(self) -> None:
        """Test None DTSTART does not set scheduled."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Task without start date",
            created=datetime.now(UTC),
            dtstart=None,
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.scheduled is None

    def test_x_taskwarrior_wait_to_wait(self) -> None:
        """Test X-TASKWARRIOR-WAIT is mapped to wait field."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Task with wait date",
            created=datetime.now(UTC),
            wait=datetime(2024, 11, 25, 8, 0, 0, tzinfo=UTC),
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.wait == datetime(2024, 11, 25, 8, 0, 0, tzinfo=UTC)

    def test_x_taskwarrior_wait_none_maps_to_no_wait(self) -> None:
        """Test None X-TASKWARRIOR-WAIT does not set wait."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Task without wait date",
            created=datetime.now(UTC),
            wait=None,
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.wait is None

    def test_completed_to_end(self) -> None:
        """Test COMPLETED timestamp is mapped to end field."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Completed task",
            status="COMPLETED",
            created=datetime.now(UTC),
            completed=datetime(2024, 11, 21, 15, 30, 0, tzinfo=UTC),
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.end == datetime(2024, 11, 21, 15, 30, 0, tzinfo=UTC)
        assert task.status == "completed"

    def test_completed_none_maps_to_no_end(self) -> None:
        """Test None COMPLETED does not set end field."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Pending task",
            status="NEEDS-ACTION",
            created=datetime.now(UTC),
            completed=None,
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.end is None
        assert task.status == "pending"

    def test_round_trip_conversion(self) -> None:
        """Test converting back and forth preserves data."""
        original_task = Task(
            uuid="12345678-1234-1234-1234-123456789012",
            description="Round trip test",
            status="pending",
            entry=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
            project="work",
            priority="H",
            due=datetime(2024, 11, 20, 12, 0, 0, tzinfo=UTC),
            scheduled=datetime(2024, 11, 19, 9, 0, 0, tzinfo=UTC),
            tags=["important"],
        )

        # Convert to CalDAV
        vtodo = taskwarrior_to_caldav(original_task)

        # Convert back to TaskWarrior
        converted_task = caldav_to_taskwarrior(vtodo, existing_task=original_task)

        # Check key fields are preserved
        assert converted_task.uuid == original_task.uuid
        assert converted_task.description == original_task.description
        assert converted_task.status == original_task.status
        # Project is not synced via CalDAV - it will be None after round trip
        # The sync engine sets project based on calendar mapping
        assert converted_task.project is None
        assert converted_task.tags == original_task.tags
        assert converted_task.priority == original_task.priority
        assert converted_task.due == original_task.due
        assert converted_task.scheduled == original_task.scheduled

    def test_annotation_deduplication(self) -> None:
        """Test that annotations are deduplicated when merging."""
        # Create existing task with annotations
        existing_task = Task(
            uuid="test-uuid",
            description="Test task",
            status="pending",
            entry=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
            annotations=[
                {"entry": "20241117T103000Z", "description": "Existing note 1"},
                {"entry": "20241117T110000Z", "description": "Existing note 2"},
            ],
        )

        # Create VTodo with overlapping and new annotations
        vtodo = VTodo(
            uid="test-uid",
            summary="Test task",
            description=(
                "--- TaskWarrior Annotations ---\n"
                "20241117T103000Z|Existing note 1\n"  # Duplicate
                "20241117T120000Z|New note 3"  # New
            ),
            created=datetime.now(UTC),
        )

        # Convert with existing task (should merge and deduplicate)
        task = caldav_to_taskwarrior(vtodo, existing_task=existing_task)

        # Should have 3 annotations total (2 existing + 1 new, no duplicate)
        assert task.annotations is not None
        assert len(task.annotations) == 3
        assert task.annotations[0]["description"] == "Existing note 1"
        assert task.annotations[1]["description"] == "Existing note 2"
        assert task.annotations[2]["description"] == "New note 3"

    def test_annotation_with_pipe_in_description(self) -> None:
        """Test annotations with pipe character in description."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Test",
            description=(
                "--- TaskWarrior Annotations ---\n"
                "20241117T103000Z|Check API | POST /users"
            ),
            created=datetime.now(UTC),
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.annotations is not None
        assert len(task.annotations) == 1
        # Description should include the pipe after split on first pipe
        assert task.annotations[0]["description"] == "Check API | POST /users"

    def test_malformed_annotation_skipped(self) -> None:
        """Test that malformed annotations are skipped with warning."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Test",
            description=(
                "--- TaskWarrior Annotations ---\n"
                "20241117T103000Z|Valid note\n"
                "Invalid line without pipe\n"  # Malformed
                "BADTIMESTAMP|Another note\n"  # Invalid timestamp
                "20241117T110000Z|Another valid note"
            ),
            created=datetime.now(UTC),
        )

        task = caldav_to_taskwarrior(vtodo)

        # Should only have 2 valid annotations
        assert task.annotations is not None
        assert len(task.annotations) == 2
        assert task.annotations[0]["description"] == "Valid note"
        assert task.annotations[1]["description"] == "Another valid note"

    def test_user_description_with_annotations(self) -> None:
        """Test CalDAV description with user text and annotations."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Test",
            description=(
                "Some user description text\n"
                "--- TaskWarrior Annotations ---\n"
                "20241117T103000Z|Note 1"
            ),
            created=datetime.now(UTC),
        )

        task = caldav_to_taskwarrior(vtodo)

        # The note is not imported: TW uses the summary as its description
        assert task.description == "Test"
        assert task.annotations is not None
        assert len(task.annotations) == 2
        assert task.annotations[0]["description"] == "Note 1"
        assert task.annotations[1]["description"] == "Some user description text"


class TestCalDAVNotes:
    """Tests for mapping a CalDAV note (DESCRIPTION text) to an annotation.

    The note is stored as one TaskWarrior annotation whose entry is one second
    before the task's own entry, so no real annotation can collide with it.
    """

    ENTRY = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    NOTE_TS = "20260101T115959Z"

    def _task(self, annotations: list[dict] | None = None) -> Task:
        return Task(
            uuid="tw-uuid",
            description="Hepatologist appointment",
            status="pending",
            entry=self.ENTRY,
            annotations=annotations,
        )

    def test_note_becomes_annotation_and_title_stays_summary(self) -> None:
        """A plain note is imported as the note annotation; title is SUMMARY."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Hepatologist appointment",
            description="Ezgu Niat clinic",
            created=self.ENTRY,
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.description == "Hepatologist appointment"
        assert task.annotations == [
            {"entry": self.NOTE_TS, "description": "Ezgu Niat clinic"}
        ]

    def test_note_entry_uses_existing_task_entry(self) -> None:
        """When updating, the note timestamp derives from the existing TW entry."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Hepatologist appointment",
            description="Ezgu Niat clinic",
            created=datetime(2030, 5, 5, 5, 5, 5, tzinfo=UTC),
        )

        task = caldav_to_taskwarrior(vtodo, existing_task=self._task())

        assert task.annotations == [
            {"entry": self.NOTE_TS, "description": "Ezgu Niat clinic"}
        ]

    def test_multiline_note_is_kept_and_normalized(self) -> None:
        """CRLF line endings and surrounding whitespace are normalized."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Title",
            description="  line one\r\nline two\n",
            created=self.ENTRY,
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.annotations == [
            {"entry": self.NOTE_TS, "description": "line one\nline two"}
        ]

    def test_edited_note_replaces_annotation(self) -> None:
        """An edited note replaces the old note annotation, not duplicates it."""
        existing = self._task(
            [
                {"entry": self.NOTE_TS, "description": "old note"},
                {"entry": "20260102T090000Z", "description": "real annotation"},
            ]
        )
        vtodo = VTodo(
            uid="test-uid",
            summary="Hepatologist appointment",
            description=(
                "new note\n--- TaskWarrior Annotations ---\n"
                "20260102T090000Z|real annotation"
            ),
        )

        task = caldav_to_taskwarrior(vtodo, existing_task=existing)

        assert task.annotations == [
            {"entry": "20260102T090000Z", "description": "real annotation"},
            {"entry": self.NOTE_TS, "description": "new note"},
        ]

    def test_removed_note_removes_annotation(self) -> None:
        """Deleting the note in CalDAV removes the note annotation."""
        existing = self._task(
            [
                {"entry": self.NOTE_TS, "description": "old note"},
                {"entry": "20260102T090000Z", "description": "real annotation"},
            ]
        )
        vtodo = VTodo(
            uid="test-uid",
            summary="Hepatologist appointment",
            description=(
                "--- TaskWarrior Annotations ---\n20260102T090000Z|real annotation"
            ),
        )

        task = caldav_to_taskwarrior(vtodo, existing_task=existing)

        assert task.annotations == [
            {"entry": "20260102T090000Z", "description": "real annotation"}
        ]

    def test_taskwarrior_to_caldav_writes_note_annotation_as_plain_note(
        self,
    ) -> None:
        """The note annotation is written as plain text, never into the block."""
        task = self._task(
            [
                {"entry": self.NOTE_TS, "description": "Ezgu Niat clinic"},
                {"entry": "20260102T090000Z", "description": "real annotation"},
            ]
        )

        vtodo = taskwarrior_to_caldav(task)

        assert vtodo.summary == "Hepatologist appointment"
        assert vtodo.description == (
            "Ezgu Niat clinic\n\nTaskwarrior annotations:\n"
            "[2026-01-02 09:00:00 UTC] real annotation"
        )

    def test_taskwarrior_note_wins_over_existing_note(self) -> None:
        """A note annotation in TW is the source when updating CalDAV."""
        task = self._task([{"entry": self.NOTE_TS, "description": "from TW"}])

        vtodo = taskwarrior_to_caldav(task, existing_description="on server")

        assert vtodo.description == "from TW"

    def test_taskwarrior_to_caldav_preserves_existing_note(self) -> None:
        """Without a note annotation in TW, the server note is carried over."""
        vtodo = taskwarrior_to_caldav(
            self._task(), existing_description="Ezgu Niat clinic"
        )

        assert vtodo.summary == "Hepatologist appointment"
        assert vtodo.description == "Ezgu Niat clinic"

    def test_existing_note_with_old_annotations_is_replaced_not_duplicated(
        self,
    ) -> None:
        """Only the note is carried over; the annotation block is rebuilt from TW."""
        existing = "My note\n--- TaskWarrior Annotations ---\n20241117T103000Z|Stale"

        vtodo = taskwarrior_to_caldav(self._task(), existing_description=existing)

        assert vtodo.description == "My note"

    def test_round_trip_is_a_fixed_point(self) -> None:
        """CalDAV -> TW -> CalDAV -> TW changes nothing after the first import."""
        original = VTodo(
            uid="test-uid",
            summary="Title",
            description=(
                "My note\n\nTaskwarrior annotations:\n[2026-01-02 09:00:00 UTC] First"
            ),
            created=self.ENTRY,
        )

        first = caldav_to_taskwarrior(original)
        written = taskwarrior_to_caldav(
            first, existing_description=original.description
        )
        second = caldav_to_taskwarrior(written, existing_task=first)

        assert written.description == original.description
        assert second.description == first.description == "Title"
        assert second.annotations == first.annotations


class TestReadableAnnotationFormat:
    """Tests for the readable annotation block in the CalDAV description."""

    ENTRY = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_multiline_annotation_uses_indented_continuation(self) -> None:
        """Extra lines of an annotation are indented under its timestamp."""
        task = Task(
            uuid="tw-uuid",
            description="Title",
            status="pending",
            entry=self.ENTRY,
            annotations=[
                {"entry": "20260102T090000Z", "description": "line one\nline two"},
            ],
        )

        vtodo = taskwarrior_to_caldav(task)

        assert vtodo.description == (
            "Taskwarrior annotations:\n[2026-01-02 09:00:00 UTC] line one\n  line two"
        )

    def test_parse_readable_block(self) -> None:
        """The readable block parses back to TW timestamps and text."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Title",
            description=(
                "A note\r\n\r\nTaskwarrior annotations:\r\n"
                "[2026-01-02 09:00:00 UTC] line one\r\n"
                "  line two\r\n"
                "\r\n"
                "  line four\r\n"
                "[2026-01-03 10:15:30 UTC] second | with pipe\r\n"
            ),
            created=self.ENTRY,
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.annotations == [
            {
                "entry": "20260102T090000Z",
                "description": "line one\nline two\n\nline four",
            },
            {"entry": "20260103T101530Z", "description": "second | with pipe"},
            {"entry": "20260101T115959Z", "description": "A note"},
        ]

    def test_continuation_survives_stripped_indentation(self) -> None:
        """A client that drops the indent still yields the same annotation."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Title",
            description=(
                "Taskwarrior annotations:\n[2026-01-02 09:00:00 UTC] line one\nline two"
            ),
            created=self.ENTRY,
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.annotations == [
            {"entry": "20260102T090000Z", "description": "line one\nline two"},
        ]

    def test_header_inside_a_sentence_is_part_of_the_note(self) -> None:
        """Only a header on its own line starts the annotation block."""
        vtodo = VTodo(
            uid="test-uid",
            summary="Title",
            description="Remember: Taskwarrior annotations: are synced",
            created=self.ENTRY,
        )

        task = caldav_to_taskwarrior(vtodo)

        assert task.annotations == [
            {
                "entry": "20260101T115959Z",
                "description": "Remember: Taskwarrior annotations: are synced",
            },
        ]

    def test_legacy_block_is_rewritten_in_readable_format(self) -> None:
        """Old pipe format is read, and written back in the readable format."""
        legacy = VTodo(
            uid="test-uid",
            summary="Title",
            description=(
                "--- TaskWarrior Annotations ---\n20260102T090000Z|added in taskwarrior"
            ),
            created=self.ENTRY,
        )

        task = caldav_to_taskwarrior(legacy)
        written = taskwarrior_to_caldav(task, existing_description=legacy.description)

        assert task.annotations == [
            {"entry": "20260102T090000Z", "description": "added in taskwarrior"},
        ]
        assert written.description == (
            "Taskwarrior annotations:\n[2026-01-02 09:00:00 UTC] added in taskwarrior"
        )
