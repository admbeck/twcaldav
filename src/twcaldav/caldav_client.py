"""CalDAV client integration module."""

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime

import caldav
from caldav.objects import Calendar as CalDAVCalendar
from icalendar import Calendar, Todo
from icalendar.cal import Component as ICalComponent

from twcaldav.logger import get_logger

# Properties twcaldav owns (the ones VTodo.to_icalendar writes). On update these
# are replaced from TaskWarrior; everything else on the existing todo (alarms,
# RELATED-TO, client X- properties) is left untouched.
MAPPED_PROPERTIES = (
    "UID",
    "SUMMARY",
    "STATUS",
    "DESCRIPTION",
    "DUE",
    "DTSTART",
    "X-TASKWARRIOR-WAIT",
    "COMPLETED",
    "PRIORITY",
    "CATEGORIES",
    "CREATED",
    "LAST-MODIFIED",
)


def _apply_update(component: ICalComponent, new: Todo) -> None:
    """Replace the mapped properties of an existing VTODO in place.

    Args:
        component: Existing VTODO component from the server.
        new: VTODO built from TaskWarrior by VTodo.to_icalendar.
    """
    for name in MAPPED_PROPERTIES:
        component.pop(name, None)
    for name, value in new.items():
        component[name] = value

    # Keep PERCENT-COMPLETE consistent with the new status
    if str(component.get("STATUS", "")) == "COMPLETED":
        component.pop("PERCENT-COMPLETE", None)
        component.add("PERCENT-COMPLETE", 100)
    elif int(component.get("PERCENT-COMPLETE", 0)) == 100:
        component.pop("PERCENT-COMPLETE")
        component.add("PERCENT-COMPLETE", 0)

    _touch(component)


def _touch(component: ICalComponent) -> None:
    """Mark a VTODO as revised: refresh DTSTAMP, increment SEQUENCE if present.

    Args:
        component: VTODO component being saved.
    """
    component.pop("DTSTAMP", None)
    component.add("DTSTAMP", datetime.now(UTC))
    if "SEQUENCE" in component:
        sequence = int(component.pop("SEQUENCE"))
        component.add("SEQUENCE", sequence + 1)


@dataclass
class VTodo:
    """Represents a CalDAV VTODO (task)."""

    uid: str
    summary: str
    status: str | None = None
    description: str | None = None
    due: datetime | None = None
    dtstart: datetime | None = None
    wait: datetime | None = None
    completed: datetime | None = None
    priority: int | None = None
    categories: list[str] | None = None
    created: datetime | None = None
    last_modified: datetime | None = None

    @classmethod
    def from_icalendar(cls, todo: ICalComponent) -> "VTodo":
        """Create VTodo from icalendar Todo component.

        Args:
            todo: icalendar Todo component.

        Returns:
            VTodo instance.
        """
        uid = str(todo.get("UID", ""))
        summary = str(todo.get("SUMMARY", ""))

        # Optional fields
        status = str(todo.get("STATUS")) if todo.get("STATUS") else None
        description = str(todo.get("DESCRIPTION")) if todo.get("DESCRIPTION") else None

        # Parse datetime fields
        due = todo.get("DUE")
        if due and hasattr(due, "dt"):
            due = due.dt
            # Convert to datetime if it's a date
            if isinstance(due, datetime):
                pass  # Already a datetime
            else:
                # It's a date, convert to datetime
                from datetime import time

                due = datetime.combine(due, time())

        dtstart = todo.get("DTSTART")
        if dtstart and hasattr(dtstart, "dt"):
            dtstart = dtstart.dt
            # Convert to datetime if it's a date
            if isinstance(dtstart, datetime):
                pass  # Already a datetime
            else:
                # It's a date, convert to datetime
                from datetime import time

                dtstart = datetime.combine(dtstart, time())

        created = todo.get("CREATED")
        if created and hasattr(created, "dt"):
            created = created.dt

        last_modified = todo.get("LAST-MODIFIED")
        if last_modified and hasattr(last_modified, "dt"):
            last_modified = last_modified.dt

        # Parse wait field (custom X-TASKWARRIOR-WAIT property)
        wait = todo.get("X-TASKWARRIOR-WAIT")
        if wait:
            if hasattr(wait, "dt"):
                # Property has a dt attribute (date/datetime)
                wait = wait.dt
                # Convert to datetime if it's a date
                if not isinstance(wait, datetime):
                    from datetime import time

                    wait = datetime.combine(wait, time())
            elif isinstance(wait, str):
                # Property is a string, parse it
                try:
                    wait_str = str(wait)
                    if wait_str.endswith("Z"):
                        wait_str = wait_str[:-1] + "+00:00"
                    wait = datetime.fromisoformat(wait_str)
                except (ValueError, AttributeError):
                    wait = None
            else:
                # Unknown type, skip
                wait = None

        # Parse completed field (COMPLETED property)
        completed = todo.get("COMPLETED")
        if completed:
            if hasattr(completed, "dt"):
                # Property has a dt attribute (date/datetime)
                completed = completed.dt
                # Convert to datetime if it's a date
                if not isinstance(completed, datetime):
                    from datetime import time

                    completed = datetime.combine(completed, time())
            elif isinstance(completed, str):
                # Property is a string, parse it
                try:
                    completed_str = str(completed)
                    if completed_str.endswith("Z"):
                        completed_str = completed_str[:-1] + "+00:00"
                    completed = datetime.fromisoformat(completed_str)
                except (ValueError, AttributeError):
                    completed = None
            else:
                # Unknown type, skip
                completed = None

        # Parse priority (CalDAV uses 1-9, where 1 is highest)
        priority = None
        if todo.get("PRIORITY"):
            with contextlib.suppress(ValueError, TypeError):
                priority = int(todo.get("PRIORITY"))

        # Parse categories
        categories = None
        if todo.get("CATEGORIES"):
            cats = todo.get("CATEGORIES")
            # icalendar might return vCategory objects or strings
            if isinstance(cats, list):
                categories = []
                for c in cats:
                    # Handle vCategory objects by getting their string representation
                    if hasattr(c, "cats"):  # vCategory has a 'cats' attribute
                        categories.extend(c.cats)
                    else:
                        categories.append(str(c))
            else:
                categories = list(cats.cats) if hasattr(cats, "cats") else [str(cats)]

        return cls(
            uid=uid,
            summary=summary,
            status=status,
            description=description,
            due=due,
            dtstart=dtstart,
            wait=wait,
            completed=completed,
            priority=priority,
            categories=categories,
            created=created,
            last_modified=last_modified,
        )

    def to_icalendar(self) -> Todo:
        """Convert VTodo to icalendar Todo component.

        Returns:
            icalendar Todo component.
        """
        todo = Todo()
        todo.add("UID", self.uid)
        todo.add("SUMMARY", self.summary)

        if self.status:
            todo.add("STATUS", self.status)
        if self.description:
            todo.add("DESCRIPTION", self.description)
        if self.due:
            todo.add("DUE", self.due)
        if self.dtstart:
            todo.add("DTSTART", self.dtstart)
        if self.wait:
            todo.add("X-TASKWARRIOR-WAIT", self.wait)
        if self.completed:
            todo.add("COMPLETED", self.completed)
        if self.priority is not None:
            todo.add("PRIORITY", self.priority)
        if self.categories:
            todo.add("CATEGORIES", self.categories)
        if self.created:
            todo.add("CREATED", self.created)
        if self.last_modified:
            todo.add("LAST-MODIFIED", self.last_modified)

        return todo


class CalDAVError(Exception):
    """Exception raised for CalDAV-related errors."""


class CalDAVClient:
    """Interface to CalDAV server."""

    def __init__(self, url: str, username: str, password: str) -> None:
        """Initialize CalDAV client.

        Args:
            url: CalDAV server URL.
            username: Username for authentication.
            password: Password for authentication.

        Raises:
            CalDAVError: If connection fails.
        """
        self.url = url
        self.username = username
        self.logger = get_logger()

        try:
            self.logger.debug(f"Connecting to CalDAV server: {url}")
            self.client = caldav.DAVClient(
                url=url, username=username, password=password
            )
            self.principal = self.client.principal()
            self.logger.debug("Successfully connected to CalDAV server")
        except Exception as e:
            raise CalDAVError(f"Failed to connect to CalDAV server: {e}") from e

    def list_calendars(self) -> list[str]:
        """List all available calendars.

        Returns:
            List of calendar names.

        Raises:
            CalDAVError: If listing fails.
        """
        try:
            calendars = self.principal.calendars()
            calendar_ids = []
            for cal in calendars:
                name = cal.name
                if name:
                    calendar_ids.append(name)
            self.logger.debug(f"Found {len(calendar_ids)} calendars")
            return calendar_ids
        except Exception as e:
            raise CalDAVError(f"Failed to list calendars: {e}") from e

    def get_calendar(self, calendar_id: str) -> CalDAVCalendar:
        """Get calendar by ID.

        Args:
            calendar_id: Calendar ID (not the display name).

        Returns:
            Calendar object.

        Raises:
            CalDAVError: If calendar not found or access fails.
        """
        try:
            calendars = self.principal.calendars()
            for cal in calendars:
                if cal.id == calendar_id:
                    self.logger.debug(f"Found calendar with ID: {calendar_id}")
                    return cal

            raise CalDAVError(f"Calendar not found with ID: {calendar_id}")
        except CalDAVError:
            raise
        except Exception as e:
            raise CalDAVError(
                f"Failed to get calendar with ID '{calendar_id}': {e}"
            ) from e

    def get_todos(self, calendar_id: str) -> list[VTodo]:
        """Get all todos from a calendar, including completed ones.

        Args:
            calendar_id: ID of calendar to query.

        Returns:
            List of VTodo objects (including completed todos).

        Raises:
            CalDAVError: If query fails.

        Note:
            This method includes completed todos to support bidirectional sync
            of task status changes.
        """
        try:
            calendar = self.get_calendar(calendar_id)
            todos = calendar.todos(include_completed=True)

            vtodos = []
            for todo in todos:
                try:
                    # Parse the icalendar data
                    cal = Calendar.from_ical(todo.data)
                    for component in cal.walk():
                        if component.name == "VTODO":
                            vtodo = VTodo.from_icalendar(component)
                            vtodos.append(vtodo)
                except Exception as e:
                    self.logger.warning(f"Failed to parse todo: {e}")
                    continue

            self.logger.debug(
                f"Retrieved {len(vtodos)} todos from calendar ID '{calendar_id}'"
            )
            return vtodos
        except CalDAVError:
            raise
        except Exception as e:
            raise CalDAVError(
                f"Failed to get todos from calendar ID '{calendar_id}': {e}"
            ) from e

    def create_todo(self, calendar_id: str, vtodo: VTodo) -> None:
        """Create a new todo in a calendar.

        Args:
            calendar_id: ID of calendar.
            vtodo: VTodo object to create.

        Raises:
            CalDAVError: If creation fails.
        """
        try:
            calendar = self.get_calendar(calendar_id)

            # Create iCalendar
            cal = Calendar()
            cal.add("PRODID", "-//twcaldav//twcaldav//EN")
            cal.add("VERSION", "2.0")
            cal.add_component(vtodo.to_icalendar())

            ical_data = cal.to_ical()

            self.logger.debug(f"Creating todo in calendar '{calendar_id}': {vtodo.uid}")
            calendar.save_todo(ical_data)
            self.logger.info(f"Created todo {vtodo.uid} in calendar '{calendar_id}'")
        except CalDAVError:
            raise
        except Exception as e:
            raise CalDAVError(
                f"Failed to create todo in calendar '{calendar_id}': {e}"
            ) from e

    def update_todo(self, calendar_id: str, vtodo: VTodo) -> None:
        """Update an existing todo.

        Args:
            calendar_id: Name of calendar.
            vtodo: VTodo object with updated data.

        Raises:
            CalDAVError: If update fails.
        """
        try:
            calendar = self.get_calendar(calendar_id)

            # Find the existing todo by UID
            todos = calendar.todos(include_completed=True)
            for todo in todos:
                cal = Calendar.from_ical(todo.data)
                for component in cal.walk():
                    if (
                        component.name == "VTODO"
                        and str(component.get("UID")) == vtodo.uid
                    ):
                        # Update in place, keeping unmapped properties,
                        # subcomponents (VALARM) and the calendar's VTIMEZONEs
                        _apply_update(component, vtodo.to_icalendar())

                        todo.data = cal.to_ical()
                        todo.save()
                        self.logger.info(
                            f"Updated todo {vtodo.uid} in calendar '{calendar_id}'"
                        )
                        return

            raise CalDAVError(f"Todo not found: {vtodo.uid}")
        except CalDAVError:
            raise
        except Exception as e:
            raise CalDAVError(
                f"Failed to update todo in calendar '{calendar_id}': {e}"
            ) from e

    def delete_todo(self, calendar_id: str, uid: str) -> None:
        """Delete a todo by UID.

        Args:
            calendar_id: Name of calendar.
            uid: UID of todo to delete.

        Raises:
            CalDAVError: If deletion fails.
        """
        try:
            calendar = self.get_calendar(calendar_id)

            # Find and delete the todo
            todos = calendar.todos(include_completed=True)
            for todo in todos:
                cal = Calendar.from_ical(todo.data)
                for component in cal.walk():
                    if component.name == "VTODO" and str(component.get("UID")) == uid:
                        todo.delete()
                        self.logger.info(
                            f"Deleted todo {uid} from calendar '{calendar_id}'"
                        )
                        return

            raise CalDAVError(f"Todo not found: {uid}")
        except CalDAVError:
            raise
        except Exception as e:
            raise CalDAVError(
                f"Failed to delete todo from calendar '{calendar_id}': {e}"
            ) from e

    def cancel_todo(self, calendar_id: str, uid: str) -> None:
        """Cancel a todo by setting its status to CANCELLED.

        This is a soft-delete operation that marks the todo as cancelled
        rather than permanently removing it.

        Args:
            calendar_id: Name of calendar.
            uid: UID of todo to cancel.

        Raises:
            CalDAVError: If cancellation fails.
        """
        try:
            calendar = self.get_calendar(calendar_id)

            # Find the existing todo by UID
            todos = calendar.todos(include_completed=True)
            for todo in todos:
                cal = Calendar.from_ical(todo.data)
                for component in cal.walk():
                    if component.name == "VTODO" and str(component.get("UID")) == uid:
                        # Update the status to CANCELLED
                        if "STATUS" in component:
                            del component["STATUS"]
                        component.add("STATUS", "CANCELLED")
                        _touch(component)

                        # Save the original calendar so VTIMEZONEs are kept
                        todo.data = cal.to_ical()
                        todo.save()
                        self.logger.info(
                            f"Cancelled todo {uid} in calendar '{calendar_id}'"
                        )
                        return

            raise CalDAVError(f"Todo not found: {uid}")
        except CalDAVError:
            raise
        except Exception as e:
            raise CalDAVError(
                f"Failed to cancel todo in calendar '{calendar_id}': {e}"
            ) from e

    def get_todo_by_uid(self, calendar_id: str, uid: str) -> VTodo | None:
        """Get a specific todo by UID.

        Args:
            calendar_id: Name of calendar.
            uid: UID of todo.

        Returns:
            VTodo object if found, None otherwise.

        Raises:
            CalDAVError: If query fails.
        """
        todos = self.get_todos(calendar_id)
        for todo in todos:
            if todo.uid == uid:
                return todo
        return None
