"""Tests for configuration module."""

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from twcaldav.config import (
    CalDAVConfig,
    Config,
    ProjectCalendarMapping,
    SyncConfig,
)


def test_config_from_dict_valid() -> None:
    """Test parsing valid configuration dictionary."""
    data = {
        "caldav": {
            "url": "https://caldav.example.com",
            "username": "testuser",
            "password": "testpass",
        },
        "mappings": [
            {
                "taskwarrior_project": "work",
                "caldav_calendar": "Work Calendar",
            },
            {
                "taskwarrior_project": "personal",
                "caldav_calendar": "Personal",
            },
        ],
        "sync": {
            "delete_tasks": True,
        },
    }

    config = Config.from_dict(data)

    assert config.caldav.url == "https://caldav.example.com"
    assert config.caldav.username == "testuser"
    assert config.caldav.password == "testpass"
    assert len(config.mappings) == 2
    assert config.mappings[0].taskwarrior_project == "work"
    assert config.mappings[0].caldav_calendar == "Work Calendar"
    assert config.sync.delete_tasks is True


def test_config_missing_caldav_section() -> None:
    """Test error when caldav section is missing."""
    data = {
        "mappings": [
            {
                "taskwarrior_project": "work",
                "caldav_calendar": "Work Calendar",
            }
        ]
    }

    with pytest.raises(ValueError, match="Missing required section: \\[caldav\\]"):
        Config.from_dict(data)


def test_config_missing_caldav_url() -> None:
    """Test error when caldav URL is missing."""
    data = {
        "caldav": {
            "username": "testuser",
            "password": "testpass",
        },
        "mappings": [
            {
                "taskwarrior_project": "work",
                "caldav_calendar": "Work Calendar",
            }
        ],
    }

    with pytest.raises(ValueError, match="Missing required field in \\[caldav\\]: url"):
        Config.from_dict(data)


def test_config_missing_mappings_section() -> None:
    """Test error when mappings section is missing."""
    data = {
        "caldav": {
            "url": "https://caldav.example.com",
            "username": "testuser",
            "password": "testpass",
        }
    }

    with pytest.raises(
        ValueError, match="Missing required section: \\[\\[mappings\\]\\]"
    ):
        Config.from_dict(data)


def test_config_empty_mappings() -> None:
    """Test error when mappings list is empty."""
    data = {
        "caldav": {
            "url": "https://caldav.example.com",
            "username": "testuser",
            "password": "testpass",
        },
        "mappings": [],
    }

    with pytest.raises(
        ValueError, match="\\[\\[mappings\\]\\] must be a non-empty list"
    ):
        Config.from_dict(data)


def test_config_missing_mapping_field() -> None:
    """Test error when mapping is missing required field."""
    data = {
        "caldav": {
            "url": "https://caldav.example.com",
            "username": "testuser",
            "password": "testpass",
        },
        "mappings": [
            {
                "taskwarrior_project": "work",
                # Missing caldav_calendar
            }
        ],
    }

    with pytest.raises(ValueError, match="Missing 'caldav_calendar' in mapping 1"):
        Config.from_dict(data)


def test_config_sync_defaults() -> None:
    """Test that sync config has proper defaults."""
    data = {
        "caldav": {
            "url": "https://caldav.example.com",
            "username": "testuser",
            "password": "testpass",
        },
        "mappings": [
            {
                "taskwarrior_project": "work",
                "caldav_calendar": "Work Calendar",
            }
        ],
        # No sync section
    }

    config = Config.from_dict(data)
    assert config.sync.delete_tasks is False


def _config_data(**sync: object) -> dict:
    """Return minimal config data with these [sync] settings."""
    return {
        "caldav": {
            "url": "https://caldav.example.com",
            "username": "testuser",
            "password": "testpass",
        },
        "mappings": [{"taskwarrior_project": "work", "caldav_calendar": "Work"}],
        "sync": sync,
    }


def test_config_sync_timezone() -> None:
    """A timezone name in [sync] is parsed."""
    config = Config.from_dict(_config_data(timezone="Europe/Berlin"))

    assert config.sync.timezone == ZoneInfo("Europe/Berlin")


def test_config_sync_timezone_default() -> None:
    """Without a timezone, the system timezone is used later."""
    config = Config.from_dict(_config_data())

    assert config.sync.timezone is None


def test_config_sync_timezone_invalid() -> None:
    """An unknown timezone name is rejected."""
    with pytest.raises(ValueError, match="timezone"):
        Config.from_dict(_config_data(timezone="Nowhere/Nothing"))


def test_get_calendar_for_project() -> None:
    """Test getting calendar for a project."""
    config = Config(
        caldav=CalDAVConfig(
            url="https://caldav.example.com",
            username="testuser",
            password="testpass",
        ),
        mappings=[
            ProjectCalendarMapping(
                taskwarrior_project="work",
                caldav_calendar="Work Calendar",
            ),
            ProjectCalendarMapping(
                taskwarrior_project="personal",
                caldav_calendar="Personal",
            ),
        ],
        sync=SyncConfig(delete_tasks=False),
    )

    assert config.get_calendar_for_project("work") == "Work Calendar"
    assert config.get_calendar_for_project("personal") == "Personal"
    assert config.get_calendar_for_project("unknown") is None


def test_get_project_for_calendar() -> None:
    """Test getting project for a calendar."""
    config = Config(
        caldav=CalDAVConfig(
            url="https://caldav.example.com",
            username="testuser",
            password="testpass",
        ),
        mappings=[
            ProjectCalendarMapping(
                taskwarrior_project="work",
                caldav_calendar="Work Calendar",
            ),
            ProjectCalendarMapping(
                taskwarrior_project="personal",
                caldav_calendar="Personal",
            ),
        ],
        sync=SyncConfig(delete_tasks=False),
    )

    assert config.get_project_for_calendar("Work Calendar") == "work"
    assert config.get_project_for_calendar("Personal") == "personal"
    assert config.get_project_for_calendar("Unknown") is None


def test_get_mapped_projects() -> None:
    """Test getting all mapped projects."""
    config = Config(
        caldav=CalDAVConfig(
            url="https://caldav.example.com",
            username="testuser",
            password="testpass",
        ),
        mappings=[
            ProjectCalendarMapping(
                taskwarrior_project="work",
                caldav_calendar="Work Calendar",
            ),
            ProjectCalendarMapping(
                taskwarrior_project="personal",
                caldav_calendar="Personal",
            ),
        ],
        sync=SyncConfig(delete_tasks=False),
    )

    projects = config.get_mapped_projects()
    assert projects == ["work", "personal"]


def test_get_mapped_calendars() -> None:
    """Test getting all mapped calendars."""
    config = Config(
        caldav=CalDAVConfig(
            url="https://caldav.example.com",
            username="testuser",
            password="testpass",
        ),
        mappings=[
            ProjectCalendarMapping(
                taskwarrior_project="work",
                caldav_calendar="Work Calendar",
            ),
            ProjectCalendarMapping(
                taskwarrior_project="personal",
                caldav_calendar="Personal",
            ),
        ],
        sync=SyncConfig(delete_tasks=False),
    )

    calendars = config.get_mapped_calendars()
    assert calendars == ["Work Calendar", "Personal"]


def test_config_from_file_not_found() -> None:
    """Test error when config file doesn't exist."""
    with pytest.raises(FileNotFoundError, match="Configuration file not found"):
        Config.from_file(Path("/nonexistent/path/config.toml"))
