"""Configuration management for twcaldav."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass
class CalDAVConfig:
    """CalDAV server configuration."""

    url: str
    username: str
    password: str


@dataclass
class ProjectCalendarMapping:
    """Mapping between TaskWarrior project and CalDAV calendar."""

    taskwarrior_project: str
    caldav_calendar: str


@dataclass
class SyncConfig:
    """Synchronization behavior configuration."""

    delete_tasks: bool = False
    # Timezone of dates without a time; None means the system timezone
    timezone: ZoneInfo | None = None


@dataclass
class Config:
    """Main configuration for twcaldav."""

    caldav: CalDAVConfig
    mappings: list[ProjectCalendarMapping]
    sync: SyncConfig

    @classmethod
    def from_file(cls, config_path: Path | None = None) -> "Config":
        """Load configuration from TOML file.

        Args:
            config_path: Path to config file. If None, uses default location.

        Returns:
            Parsed configuration.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            ValueError: If config is invalid.
        """
        if config_path is None:
            config_path = Path.home() / ".config" / "twcaldav" / "config.toml"

        if not config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {config_path}\n"
                f"Please create a configuration file at {config_path}"
            )

        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Parse configuration from dictionary.

        Args:
            data: Configuration dictionary from TOML.

        Returns:
            Parsed configuration.

        Raises:
            ValueError: If configuration is invalid.
        """
        # Validate required sections
        if "caldav" not in data:
            raise ValueError("Missing required section: [caldav]")
        if "mappings" not in data:
            raise ValueError("Missing required section: [[mappings]]")

        # Parse CalDAV config
        caldav_data = data["caldav"]
        required_caldav_fields = ["url", "username", "password"]
        for field in required_caldav_fields:
            if field not in caldav_data:
                raise ValueError(f"Missing required field in [caldav]: {field}")

        caldav = CalDAVConfig(
            url=caldav_data["url"],
            username=caldav_data["username"],
            password=caldav_data["password"],
        )

        # Parse mappings
        mappings_data = data["mappings"]
        if not isinstance(mappings_data, list) or len(mappings_data) == 0:
            raise ValueError("[[mappings]] must be a non-empty list")

        mappings = []
        for idx, mapping in enumerate(mappings_data):
            if "taskwarrior_project" not in mapping:
                raise ValueError(f"Missing 'taskwarrior_project' in mapping {idx + 1}")
            if "caldav_calendar" not in mapping:
                raise ValueError(f"Missing 'caldav_calendar' in mapping {idx + 1}")

            mappings.append(
                ProjectCalendarMapping(
                    taskwarrior_project=mapping["taskwarrior_project"],
                    caldav_calendar=mapping["caldav_calendar"],
                )
            )

        # Parse sync config (optional)
        sync_data = data.get("sync", {})
        timezone = None
        if timezone_name := sync_data.get("timezone"):
            try:
                timezone = ZoneInfo(timezone_name)
            except (ZoneInfoNotFoundError, ValueError) as e:
                raise ValueError(f"Unknown timezone in [sync]: {timezone_name}") from e
        sync = SyncConfig(
            delete_tasks=sync_data.get("delete_tasks", False), timezone=timezone
        )

        return cls(caldav=caldav, mappings=mappings, sync=sync)

    def get_calendar_for_project(self, project: str) -> str | None:
        """Get CalDAV calendar name for a TaskWarrior project.

        Args:
            project: TaskWarrior project name.

        Returns:
            CalDAV calendar name, or None if not mapped.
        """
        for mapping in self.mappings:
            if mapping.taskwarrior_project == project:
                return mapping.caldav_calendar
        return None

    def get_project_for_calendar(self, calendar: str) -> str | None:
        """Get TaskWarrior project name for a CalDAV calendar.

        Args:
            calendar: CalDAV calendar name.

        Returns:
            TaskWarrior project name, or None if not mapped.
        """
        for mapping in self.mappings:
            if mapping.caldav_calendar == calendar:
                return mapping.taskwarrior_project
        return None

    def get_mapped_projects(self) -> list[str]:
        """Get list of all mapped TaskWarrior projects.

        Returns:
            List of project names.
        """
        return [m.taskwarrior_project for m in self.mappings]

    def get_mapped_calendars(self) -> list[str]:
        """Get list of all mapped CalDAV calendars.

        Returns:
            List of calendar names.
        """
        return [m.caldav_calendar for m in self.mappings]
