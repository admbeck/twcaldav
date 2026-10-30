# twcaldav

[![Test](https://github.com/admbeck/twcaldav/actions/workflows/test.yml/badge.svg)](https://github.com/admbeck/twcaldav/actions/workflows/test.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Bidirectional synchronization between TaskWarrior and CalDAV servers.

> [!WARNING]
>
> This project was completely coded by an AI agent. A human was involved in
> describing the project, making implementation and behavior decisions, defining
> required tests, and spotting errors, among other things. However, so far, the
> human has NOT written or corrected a single line of code directly. What a time
> to be alive.
>
> Also, this program may destroy your data (not because it was made by robots).
> Always use `--dry-run` before syncing anything important.

## Features

- 🔄 **Bidirectional Sync** - Changes propagate both ways (TaskWarrior ↔
  CalDAV).
- 💾 **No Sync Database** - CalDAV UID is stored as a TaskWarrior
  [UDA](https://taskwarrior.org/docs/udas/), so there is no need for an
  intermediate sync database.
- 🖥️ **Multi-Client Support** - Multiple TaskWarrior instances can sync against
  the same CalDAV server.
- 🎯 **Project Mapping** - One TaskWarrior project maps to one CalDAV calendar.
- 🔍 **LWW Conflict Resolution** - Timestamp-based conflict resolution. Last
  Write Wins.
- 🧪 **Dry Run Mode** - Preview changes before syncing.
- ✅ **Comprehensive Tests** - Extensive unit tests, plus integration tests
  performed in Docker to replicate actual usage.

## Installation

### Using uv

```bash
uv tool install git+https://github.com/pcaro90/twcaldav
twcaldav --version
```

### Using pipx

```bash
pipx install git+https://github.com/pcaro90/twcaldav
twcaldav --version
```

### Run using uvx (without installing)

```bash
uvx --from git+https://github.com/pcaro90/twcaldav.git twcaldav --version
```

## Quick Start

### 1. Configure TaskWarrior UDA

**IMPORTANT**: Before first sync, configure TaskWarrior to recognize the CalDAV
UID as a User Defined Attribute:

```bash
task config uda.caldav_uid.type string
task config uda.caldav_uid.label "CalDAV UID"
```

This allows twcaldav to store the CalDAV task identifier in your TaskWarrior
database, enabling proper synchronization across multiple devices.

### 2. Create Configuration File

Create `~/.config/twcaldav/config.toml`, using `config.toml.example` as a
starting point. All options are documented in the example file.

### 3. Run Sync

```bash
# Test CalDAV connection
twcaldav test-caldav

# Preview changes without applying them
twcaldav sync --dry-run --verbose

# Perform actual synchronization
twcaldav sync --verbose
```

### 4. Set Up Automated Sync (Optional)

To sync automatically every hour:

```bash
# Edit crontab
crontab -e

# Add this line (adjust path based on your installation method):
0 * * * * /path/to/twcaldav sync >> /var/log/twcaldav.log 2>&1
```

Alternatively, use a systemd timer:

```ini
# ~/.config/systemd/user/twcaldav.service
[Unit]
Description=TaskWarrior CalDAV Sync

[Service]
Type=oneshot
ExecStart=/path/to/twcaldav sync

# ~/.config/systemd/user/twcaldav.timer
[Unit]
Description=Run TaskWarrior CalDAV Sync hourly

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

Enable with:

```bash
systemctl --user enable --now twcaldav.timer
```

## Field Mapping

| TaskWarrior      | CalDAV                                             |
| ---------------- | -------------------------------------------------- |
| description      | SUMMARY                                            |
| status           | STATUS (pending→NEEDS-ACTION, completed→COMPLETED) |
| end              | COMPLETED (completion timestamp)                   |
| due              | DUE                                                |
| scheduled        | DTSTART (start date/time)                          |
| wait             | X-TASKWARRIOR-WAIT (custom property)               |
| priority         | PRIORITY (H→1, M→5, L→9)                           |
| project          | CATEGORIES                                         |
| tags             | CATEGORIES                                         |
| annotations      | DESCRIPTION                                        |
| caldav_uid (UDA) | UID (unique identifier)                            |

## Testing

The project has comprehensive test coverage, including both unit tests and
end-to-end integration tests with a real CalDAV + TaskWarrior environment
(Docker-based).

```bash
# Run unit tests
uv run pytest -v

# Run integration tests (requires Docker)
./scripts/run-integration-tests.sh
```

## CI/CD

The project uses GitHub Actions for automated testing:

- **Lint**: Code quality checks with Ruff
- **Unit Tests**: Fast, mocked tests
- **Integration Tests**: Full end-to-end tests with Docker

Every push and pull request triggers the full test suite.

## Alternatives

Similar projects you might want to consider:

- [syncall](https://github.com/bergercookie/syncall) - Bidirectional
  synchronization between taskwarrior, Google Calendar, Notion, Asana, and more
- [caldavwarrior](https://gitlab.com/BlackEdder/caldavwarrior) - Synchronize
  TaskWarrior with CalDAV servers
- [calwarrior](https://github.com/erikh/calwarrior) - CalDAV to TaskWarrior sync
  utility

## Roadmap

Future improvements planned:

- [ ] Task dependency synchronization
- [x] Task scheduled/start time mapping

## License

MIT License - see LICENSE file for details

## Credits

- Built with [caldav](https://github.com/python-caldav/caldav) library
- Uses [TaskWarrior](https://taskwarrior.org/) CLI
- Tested with [Radicale](https://radicale.org/) CalDAV server
