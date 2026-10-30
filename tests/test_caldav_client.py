"""Tests for CalDAV client module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from icalendar import Calendar, Todo

from twcaldav.caldav_client import CalDAVClient, CalDAVError, VTodo


class TestVTodo:
    """Tests for VTodo dataclass."""

    def test_from_icalendar_minimal(self) -> None:
        """Test creating VTodo from minimal icalendar component."""
        todo = Todo()
        todo.add("UID", "test-uid-123")
        todo.add("SUMMARY", "Test task")

        vtodo = VTodo.from_icalendar(todo)

        assert vtodo.uid == "test-uid-123"
        assert vtodo.summary == "Test task"
        assert vtodo.status is None
        assert vtodo.description is None
        assert vtodo.due is None

    def test_from_icalendar_full(self) -> None:
        """Test creating VTodo from complete icalendar component."""
        todo = Todo()
        todo.add("UID", "test-uid-123")
        todo.add("SUMMARY", "Complete task")
        todo.add("STATUS", "NEEDS-ACTION")
        todo.add("DESCRIPTION", "Task description")
        todo.add("DUE", datetime(2024, 11, 20, 12, 0, 0, tzinfo=UTC))
        todo.add("PRIORITY", 5)
        todo.add("CATEGORIES", ["work", "important"])
        todo.add("CREATED", datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC))
        todo.add("LAST-MODIFIED", datetime(2024, 11, 17, 11, 0, 0, tzinfo=UTC))

        vtodo = VTodo.from_icalendar(todo)

        assert vtodo.uid == "test-uid-123"
        assert vtodo.summary == "Complete task"
        assert vtodo.status == "NEEDS-ACTION"
        assert vtodo.description == "Task description"
        assert vtodo.due == datetime(2024, 11, 20, 12, 0, 0, tzinfo=UTC)
        assert vtodo.priority == 5
        assert vtodo.categories == ["work", "important"]

    def test_to_icalendar_minimal(self) -> None:
        """Test converting minimal VTodo to icalendar."""
        vtodo = VTodo(
            uid="test-uid-123",
            summary="Test task",
        )

        todo = vtodo.to_icalendar()

        assert str(todo.get("UID")) == "test-uid-123"
        assert str(todo.get("SUMMARY")) == "Test task"
        assert todo.get("STATUS") is None

    def test_to_icalendar_full(self) -> None:
        """Test converting complete VTodo to icalendar."""
        vtodo = VTodo(
            uid="test-uid-123",
            summary="Complete task",
            status="NEEDS-ACTION",
            description="Task description",
            due=datetime(2024, 11, 20, 12, 0, 0, tzinfo=UTC),
            priority=5,
            categories=["work", "important"],
            created=datetime(2024, 11, 17, 10, 0, 0, tzinfo=UTC),
            last_modified=datetime(2024, 11, 17, 11, 0, 0, tzinfo=UTC),
        )

        todo = vtodo.to_icalendar()

        assert str(todo.get("UID")) == "test-uid-123"
        assert str(todo.get("SUMMARY")) == "Complete task"
        assert str(todo.get("STATUS")) == "NEEDS-ACTION"
        assert str(todo.get("DESCRIPTION")) == "Task description"
        assert todo.get("PRIORITY") == 5
        # X-TASKWARRIOR-UUID no longer included (using UDA instead)


class TestCalDAVClient:
    """Tests for CalDAVClient class."""

    @patch("caldav.DAVClient")
    def test_init_success(self, mock_dav_client) -> None:
        """Test successful initialization."""
        mock_principal = Mock()
        mock_client_instance = Mock()
        mock_client_instance.principal.return_value = mock_principal
        mock_dav_client.return_value = mock_client_instance

        client = CalDAVClient(
            url="https://caldav.example.com", username="user", password="pass"
        )

        assert client.url == "https://caldav.example.com"
        assert client.username == "user"
        mock_dav_client.assert_called_once()

    @patch("caldav.DAVClient")
    def test_init_connection_failure(self, mock_dav_client) -> None:
        """Test initialization with connection failure."""
        mock_dav_client.side_effect = Exception("Connection failed")

        with pytest.raises(CalDAVError, match="Failed to connect"):
            CalDAVClient(
                url="https://caldav.example.com", username="user", password="pass"
            )

    @patch("caldav.DAVClient")
    def test_list_calendars(self, mock_dav_client) -> None:
        """Test listing calendars."""
        mock_cal1 = Mock()
        mock_cal1.name = "Work"
        mock_cal2 = Mock()
        mock_cal2.name = "Personal"

        mock_principal = Mock()
        mock_principal.calendars.return_value = [mock_cal1, mock_cal2]

        mock_client_instance = Mock()
        mock_client_instance.principal.return_value = mock_principal
        mock_dav_client.return_value = mock_client_instance

        client = CalDAVClient(
            url="https://caldav.example.com", username="user", password="pass"
        )
        calendars = client.list_calendars()

        assert calendars == ["Work", "Personal"]

    @patch("caldav.DAVClient")
    def test_get_calendar_found(self, mock_dav_client) -> None:
        """Test getting calendar by ID."""
        mock_cal1 = Mock()
        mock_cal1.id = "Work"
        mock_cal2 = Mock()
        mock_cal2.id = "Personal"

        mock_principal = Mock()
        mock_principal.calendars.return_value = [mock_cal1, mock_cal2]

        mock_client_instance = Mock()
        mock_client_instance.principal.return_value = mock_principal
        mock_dav_client.return_value = mock_client_instance

        client = CalDAVClient(
            url="https://caldav.example.com", username="user", password="pass"
        )
        calendar = client.get_calendar("Work")

        assert calendar == mock_cal1

    @patch("caldav.DAVClient")
    def test_get_calendar_not_found(self, mock_dav_client) -> None:
        """Test getting non-existent calendar."""
        mock_cal = Mock()
        mock_cal.id = "Work"

        mock_principal = Mock()
        mock_principal.calendars.return_value = [mock_cal]

        mock_client_instance = Mock()
        mock_client_instance.principal.return_value = mock_principal
        mock_dav_client.return_value = mock_client_instance

        client = CalDAVClient(
            url="https://caldav.example.com", username="user", password="pass"
        )

        with pytest.raises(CalDAVError, match="Calendar not found"):
            client.get_calendar("NonExistent")

    @patch("caldav.DAVClient")
    def test_get_todos(self, mock_dav_client) -> None:
        """Test getting todos from calendar."""
        # Create mock todo
        todo_component = Todo()
        todo_component.add("UID", "test-uid-123")
        todo_component.add("SUMMARY", "Test task")

        cal = Calendar()
        cal.add_component(todo_component)

        mock_todo = Mock()
        mock_todo.data = cal.to_ical()

        mock_calendar = Mock()
        mock_calendar.id = "Work"
        mock_calendar.todos.return_value = [mock_todo]

        mock_principal = Mock()
        mock_principal.calendars.return_value = [mock_calendar]

        mock_client_instance = Mock()
        mock_client_instance.principal.return_value = mock_principal
        mock_dav_client.return_value = mock_client_instance

        client = CalDAVClient(
            url="https://caldav.example.com", username="user", password="pass"
        )
        todos = client.get_todos("Work")

        assert len(todos) == 1
        assert todos[0].uid == "test-uid-123"
        assert todos[0].summary == "Test task"

    @patch("caldav.DAVClient")
    def test_create_todo(self, mock_dav_client) -> None:
        """Test creating a todo."""
        mock_calendar = Mock()
        mock_calendar.id = "Work"
        mock_calendar.save_todo = Mock()

        mock_principal = Mock()
        mock_principal.calendars.return_value = [mock_calendar]

        mock_client_instance = Mock()
        mock_client_instance.principal.return_value = mock_principal
        mock_dav_client.return_value = mock_client_instance

        client = CalDAVClient(
            url="https://caldav.example.com", username="user", password="pass"
        )

        vtodo = VTodo(uid="test-uid-123", summary="Test task")
        client.create_todo("Work", vtodo)

        mock_calendar.save_todo.assert_called_once()

    @patch("caldav.DAVClient")
    def test_delete_todo(self, mock_dav_client) -> None:
        """Test deleting a todo."""
        # Create mock todo
        todo_component = Todo()
        todo_component.add("UID", "test-uid-123")
        todo_component.add("SUMMARY", "Test task")

        cal = Calendar()
        cal.add_component(todo_component)

        mock_todo = Mock()
        mock_todo.data = cal.to_ical()
        mock_todo.delete = Mock()

        mock_calendar = Mock()
        mock_calendar.id = "Work"
        mock_calendar.todos.return_value = [mock_todo]

        mock_principal = Mock()
        mock_principal.calendars.return_value = [mock_calendar]

        mock_client_instance = Mock()
        mock_client_instance.principal.return_value = mock_principal
        mock_dav_client.return_value = mock_client_instance

        client = CalDAVClient(
            url="https://caldav.example.com", username="user", password="pass"
        )
        client.delete_todo("Work", "test-uid-123")

        mock_todo.delete.assert_called_once()

    @patch("caldav.DAVClient")
    def test_get_todo_by_uid(self, mock_dav_client) -> None:
        """Test getting todo by UID."""
        # Create mock todos
        todo1 = Todo()
        todo1.add("UID", "test-uid-123")
        todo1.add("SUMMARY", "Task 1")

        todo2 = Todo()
        todo2.add("UID", "test-uid-456")
        todo2.add("SUMMARY", "Task 2")

        cal1 = Calendar()
        cal1.add_component(todo1)
        cal2 = Calendar()
        cal2.add_component(todo2)

        mock_todo1 = Mock()
        mock_todo1.data = cal1.to_ical()
        mock_todo2 = Mock()
        mock_todo2.data = cal2.to_ical()

        mock_calendar = Mock()
        mock_calendar.id = "Work"
        mock_calendar.todos.return_value = [mock_todo1, mock_todo2]

        mock_principal = Mock()
        mock_principal.calendars.return_value = [mock_calendar]

        mock_client_instance = Mock()
        mock_client_instance.principal.return_value = mock_principal
        mock_dav_client.return_value = mock_client_instance

        client = CalDAVClient(
            url="https://caldav.example.com", username="user", password="pass"
        )
        todo = client.get_todo_by_uid("Work", "test-uid-456")

        assert todo is not None
        assert todo.uid == "test-uid-456"
        assert todo.summary == "Task 2"

    @patch("caldav.DAVClient")
    def test_cancel_todo(self, mock_dav_client) -> None:
        """Test cancelling a todo (setting status to CANCELLED)."""
        # Create mock todo with NEEDS-ACTION status
        todo_component = Todo()
        todo_component.add("UID", "test-uid-123")
        todo_component.add("SUMMARY", "Test task")
        todo_component.add("STATUS", "NEEDS-ACTION")

        cal = Calendar()
        cal.add_component(todo_component)

        mock_todo = Mock()
        mock_todo.data = cal.to_ical()
        mock_todo.save = Mock()

        mock_calendar = Mock()
        mock_calendar.id = "Work"
        mock_calendar.todos.return_value = [mock_todo]

        mock_principal = Mock()
        mock_principal.calendars.return_value = [mock_calendar]

        mock_client_instance = Mock()
        mock_client_instance.principal.return_value = mock_principal
        mock_dav_client.return_value = mock_client_instance

        client = CalDAVClient(
            url="https://caldav.example.com", username="user", password="pass"
        )
        client.cancel_todo("Work", "test-uid-123")

        # Verify save was called
        mock_todo.save.assert_called_once()

        # Verify the updated data has CANCELLED status
        updated_cal = Calendar.from_ical(mock_todo.data)
        for component in updated_cal.walk():
            if component.name == "VTODO":
                assert str(component.get("STATUS")) == "CANCELLED"

    @patch("caldav.DAVClient")
    def test_cancel_todo_not_found(self, mock_dav_client) -> None:
        """Test cancelling a non-existent todo."""
        mock_calendar = Mock()
        mock_calendar.id = "Work"
        mock_calendar.todos.return_value = []

        mock_principal = Mock()
        mock_principal.calendars.return_value = [mock_calendar]

        mock_client_instance = Mock()
        mock_client_instance.principal.return_value = mock_principal
        mock_dav_client.return_value = mock_client_instance

        client = CalDAVClient(
            url="https://caldav.example.com", username="user", password="pass"
        )

        with pytest.raises(CalDAVError, match="Todo not found"):
            client.cancel_todo("Work", "nonexistent-uid")


EXISTING_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:+//IDN tasks.org//android-140100//EN
BEGIN:VTIMEZONE
TZID:Asia/Tashkent
BEGIN:STANDARD
TZOFFSETFROM:+0500
TZOFFSETTO:+0500
TZNAME:+05
DTSTART:19700101T000000
END:STANDARD
END:VTIMEZONE
BEGIN:VTODO
UID:test-uid-123
DTSTAMP:20260101T000000Z
SEQUENCE:3
SUMMARY:Old title
STATUS:NEEDS-ACTION
DESCRIPTION:Old note
PRIORITY:9
DUE;TZID=Asia/Tashkent:20260725T110001
PERCENT-COMPLETE:0
RELATED-TO;RELTYPE=PARENT:parent-uid-456
X-APPLE-SORT-ORDER:123456
X-MOZ-SNOOZE-TIME:20260724T100000Z
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Default Tasks.org description
TRIGGER;RELATED=END:PT0S
END:VALARM
END:VTODO
END:VCALENDAR
"""


def _client_with_todo(mock_dav_client, ics: str) -> tuple[CalDAVClient, Mock]:
    """Build a CalDAVClient whose 'Work' calendar holds one todo with this data."""
    mock_todo = Mock()
    mock_todo.data = ics.replace("\n", "\r\n").encode()
    mock_todo.save = Mock()

    mock_calendar = Mock()
    mock_calendar.id = "Work"
    mock_calendar.todos.return_value = [mock_todo]

    mock_principal = Mock()
    mock_principal.calendars.return_value = [mock_calendar]

    mock_client_instance = Mock()
    mock_client_instance.principal.return_value = mock_principal
    mock_dav_client.return_value = mock_client_instance

    client = CalDAVClient(
        url="https://caldav.example.com", username="user", password="pass"
    )
    return client, mock_todo


def _saved_todo(mock_todo: Mock) -> tuple[Calendar, Todo]:
    """Return the saved calendar and its VTODO component."""
    cal = Calendar.from_ical(mock_todo.data)
    return cal, next(iter(cal.walk("VTODO")))


class TestUpdateTodo:
    """Tests for updating an existing todo in place."""

    @patch("caldav.DAVClient")
    def test_updates_mapped_properties(self, mock_dav_client) -> None:
        """Mapped properties take the new values."""
        client, mock_todo = _client_with_todo(mock_dav_client, EXISTING_ICS)

        client.update_todo(
            "Work",
            VTodo(
                uid="test-uid-123",
                summary="New title",
                status="NEEDS-ACTION",
                description="New note",
                due=datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC),
                priority=1,
            ),
        )

        mock_todo.save.assert_called_once()
        _, todo = _saved_todo(mock_todo)
        assert str(todo["SUMMARY"]) == "New title"
        assert str(todo["DESCRIPTION"]) == "New note"
        assert todo["PRIORITY"] == 1
        assert todo.decoded("DUE") == datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC)

    @patch("caldav.DAVClient")
    def test_preserves_unmapped_properties(self, mock_dav_client) -> None:
        """Alarms, subtask links and client properties survive an update."""
        client, mock_todo = _client_with_todo(mock_dav_client, EXISTING_ICS)

        client.update_todo("Work", VTodo(uid="test-uid-123", summary="New title"))

        cal, todo = _saved_todo(mock_todo)
        assert str(todo["RELATED-TO"]) == "parent-uid-456"
        assert todo["RELATED-TO"].params["RELTYPE"] == "PARENT"
        assert str(todo["X-APPLE-SORT-ORDER"]) == "123456"
        assert "X-MOZ-SNOOZE-TIME" in todo
        alarms = [c for c in todo.subcomponents if c.name == "VALARM"]
        assert len(alarms) == 1
        assert alarms[0].decoded("TRIGGER") == timedelta(0)
        assert alarms[0]["TRIGGER"].params["RELATED"] == "END"

    @patch("caldav.DAVClient")
    def test_keeps_vtimezone(self, mock_dav_client) -> None:
        """The calendar's VTIMEZONE is kept so TZID references stay valid."""
        client, mock_todo = _client_with_todo(mock_dav_client, EXISTING_ICS)

        client.update_todo("Work", VTodo(uid="test-uid-123", summary="New title"))

        cal, _ = _saved_todo(mock_todo)
        assert [str(tz["TZID"]) for tz in cal.walk("VTIMEZONE")] == ["Asia/Tashkent"]

    @patch("caldav.DAVClient")
    def test_removes_mapped_properties_absent_from_update(
        self, mock_dav_client
    ) -> None:
        """A field cleared in TaskWarrior is removed from the todo."""
        client, mock_todo = _client_with_todo(mock_dav_client, EXISTING_ICS)

        client.update_todo("Work", VTodo(uid="test-uid-123", summary="New title"))

        _, todo = _saved_todo(mock_todo)
        for name in ("DUE", "DESCRIPTION", "PRIORITY", "STATUS"):
            assert name not in todo

    @patch("caldav.DAVClient")
    def test_bumps_sequence_and_dtstamp(self, mock_dav_client) -> None:
        """SEQUENCE is incremented and DTSTAMP refreshed."""
        client, mock_todo = _client_with_todo(mock_dav_client, EXISTING_ICS)
        before = datetime.now(UTC).replace(microsecond=0)

        client.update_todo("Work", VTodo(uid="test-uid-123", summary="New title"))

        _, todo = _saved_todo(mock_todo)
        assert todo["SEQUENCE"] == 4
        assert todo.decoded("DTSTAMP") >= before

    @patch("caldav.DAVClient")
    def test_completed_sets_percent_complete(self, mock_dav_client) -> None:
        """Completing a todo sets PERCENT-COMPLETE to 100."""
        client, mock_todo = _client_with_todo(mock_dav_client, EXISTING_ICS)

        client.update_todo(
            "Work",
            VTodo(
                uid="test-uid-123",
                summary="Old title",
                status="COMPLETED",
                completed=datetime(2026, 7, 25, 6, 16, 20, tzinfo=UTC),
            ),
        )

        _, todo = _saved_todo(mock_todo)
        assert todo["PERCENT-COMPLETE"] == 100

    @patch("caldav.DAVClient")
    def test_reopened_resets_percent_complete(self, mock_dav_client) -> None:
        """Reopening a completed todo resets PERCENT-COMPLETE from 100 to 0."""
        completed_ics = EXISTING_ICS.replace(
            "STATUS:NEEDS-ACTION", "STATUS:COMPLETED\nCOMPLETED:20260725T061620Z"
        ).replace("PERCENT-COMPLETE:0", "PERCENT-COMPLETE:100")
        client, mock_todo = _client_with_todo(mock_dav_client, completed_ics)

        client.update_todo(
            "Work",
            VTodo(uid="test-uid-123", summary="Old title", status="NEEDS-ACTION"),
        )

        _, todo = _saved_todo(mock_todo)
        assert todo["PERCENT-COMPLETE"] == 0
        assert "COMPLETED" not in todo

    @patch("caldav.DAVClient")
    def test_update_not_found(self, mock_dav_client) -> None:
        """Updating an unknown UID raises CalDAVError."""
        client, mock_todo = _client_with_todo(mock_dav_client, EXISTING_ICS)

        with pytest.raises(CalDAVError, match="Todo not found"):
            client.update_todo("Work", VTodo(uid="other-uid", summary="X"))
        mock_todo.save.assert_not_called()


class TestCancelTodoPreservation:
    """cancel_todo edits in place too."""

    @patch("caldav.DAVClient")
    def test_cancel_keeps_vtimezone_and_alarm(self, mock_dav_client) -> None:
        """Cancelling keeps VTIMEZONE, alarms and other properties."""
        client, mock_todo = _client_with_todo(mock_dav_client, EXISTING_ICS)

        client.cancel_todo("Work", "test-uid-123")

        cal, todo = _saved_todo(mock_todo)
        assert str(todo["STATUS"]) == "CANCELLED"
        assert [str(tz["TZID"]) for tz in cal.walk("VTIMEZONE")] == ["Asia/Tashkent"]
        assert [c.name for c in todo.subcomponents] == ["VALARM"]
        assert str(todo["RELATED-TO"]) == "parent-uid-456"
