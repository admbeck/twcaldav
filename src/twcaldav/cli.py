"""Command-line interface for twcaldav."""

import argparse
import sys
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command-line arguments. If None, uses sys.argv.

    Returns:
        Parsed arguments.
    """
    from . import __version__

    # Main parser
    parser = argparse.ArgumentParser(
        prog="twcaldav",
        description="Bi-directional sync between TaskWarrior and CalDAV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Sync subcommand
    sync_parser = subparsers.add_parser(
        "sync",
        help="Synchronize TaskWarrior and CalDAV",
        description=(
            "Perform bi-directional synchronization between TaskWarrior and CalDAV"
        ),
    )
    sync_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output (DEBUG level)",
    )
    sync_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        metavar="PATH",
        help="Path to configuration file (default: ~/.config/twcaldav/config.toml)",
    )
    sync_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Perform a trial run with no changes made",
    )
    sync_parser.add_argument(
        "--delete",
        action="store_true",
        help="Enable deletion of tasks (overrides config setting)",
    )
    sync_parser.add_argument(
        "--no-delete",
        action="store_true",
        help="Disable deletion of tasks (overrides config setting)",
    )

    # Unlink subcommand
    unlink_parser = subparsers.add_parser(
        "unlink",
        help="Remove CalDAV UID from TaskWarrior tasks",
        description="Remove the caldav_uid field from TaskWarrior tasks",
    )
    unlink_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output (DEBUG level)",
    )
    unlink_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        metavar="PATH",
        help="Path to configuration file (default: ~/.config/twcaldav/config.toml)",
    )
    unlink_parser.add_argument(
        "--project",
        type=str,
        metavar="PROJECT",
        help="Filter by project name (default: all projects)",
    )
    unlink_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    unlink_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be unlinked without making changes",
    )

    # Test-caldav subcommand
    test_parser = subparsers.add_parser(
        "test-caldav",
        help="Test CalDAV server connection",
        description="Test connection to CalDAV server and list available calendars",
    )
    test_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output (DEBUG level)",
    )
    test_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        metavar="PATH",
        help="Path to configuration file (default: ~/.config/twcaldav/config.toml)",
    )

    args = parser.parse_args(argv)

    # If no subcommand specified, show help and exit
    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Validate conflicting options for sync command
    if (
        (
            args.command == "sync"
            and hasattr(args, "delete")
            and hasattr(args, "no_delete")
        )
        and args.delete
        and args.no_delete
    ):
        parser.error("--delete and --no-delete cannot be used together")

    return args


def cmd_sync(args: argparse.Namespace) -> int:
    """Execute the sync command.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    from .caldav_client import CalDAVClient
    from .config import Config
    from .logger import setup_logger
    from .sync_engine import SyncEngine
    from .taskwarrior import TaskWarrior

    # Setup logging
    logger = setup_logger(verbose=args.verbose)

    logger.info("Starting twcaldav sync")

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    # Load configuration
    try:
        config = Config.from_file(args.config)
        logger.debug(f"Loaded configuration from {args.config or 'default location'}")
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    # Handle deletion override
    delete_enabled = config.sync.delete_tasks
    if args.delete:
        delete_enabled = True
        logger.info("Deletion enabled via command-line flag")
    elif args.no_delete:
        delete_enabled = False
        logger.info("Deletion disabled via command-line flag")

    # Update config with deletion override
    config.sync.delete_tasks = delete_enabled

    logger.debug(f"CalDAV URL: {config.caldav.url}")
    logger.debug(f"CalDAV Username: {config.caldav.username}")
    logger.debug(f"Mapped projects: {config.get_mapped_projects()}")
    logger.debug(f"Mapped calendars: {config.get_mapped_calendars()}")
    logger.debug(f"Delete tasks: {delete_enabled}")

    # Initialize clients
    try:
        logger.debug("Initializing TaskWarrior client")
        tw = TaskWarrior()

        # Validate required UDA
        logger.debug("Validating TaskWarrior UDA configuration")
        if not tw.validate_uda("caldav_uid"):
            logger.error(
                "Required UDA 'caldav_uid' is not configured in TaskWarrior.\n"
                "\n"
                "Please add the following to your ~/.taskrc file:\n"
                "\n"
                "  uda.caldav_uid.type=string\n"
                "  uda.caldav_uid.label=CalDAV UID\n"
                "\n"
                "Then run 'task udas' to verify the configuration."
            )
            return 1

        logger.debug("Connecting to CalDAV server")
        caldav_client = CalDAVClient(
            url=config.caldav.url,
            username=config.caldav.username,
            password=config.caldav.password,
        )
    except Exception as e:
        logger.error(f"Failed to initialize clients: {e}")
        return 1

    # Initialize sync engine
    logger.debug("Initializing sync engine")
    sync_engine = SyncEngine(
        config=config,
        tw=tw,
        caldav_client=caldav_client,
        dry_run=args.dry_run,
    )

    # Perform synchronization
    try:
        logger.info("Starting synchronization")
        stats = sync_engine.sync()

        # Display results
        logger.info("Synchronization completed")
        print()
        print(stats)

        if stats.errors > 0:
            logger.warning(f"Sync completed with {stats.errors} error(s)")
            return 1

        return 0

    except Exception as e:
        logger.error(f"Synchronization failed: {e}")
        logger.debug("Exception details:", exc_info=True)
        return 1


def cmd_unlink(args: argparse.Namespace) -> int:
    """Execute the unlink command.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    from .config import Config
    from .logger import setup_logger
    from .taskwarrior import TaskWarrior

    # Setup logging
    logger = setup_logger(verbose=args.verbose)

    logger.info("Starting twcaldav unlink")

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    # Load configuration (for validation only)
    try:
        Config.from_file(args.config)
        logger.debug(f"Loaded configuration from {args.config or 'default location'}")
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    # Initialize TaskWarrior client
    try:
        logger.debug("Initializing TaskWarrior client")
        tw = TaskWarrior()

        # Validate required UDA
        if not tw.validate_uda("caldav_uid"):
            logger.error("Required UDA 'caldav_uid' is not configured in TaskWarrior.")
            return 1

    except Exception as e:
        logger.error(f"Failed to initialize TaskWarrior client: {e}")
        return 1

    # Build filter for tasks with caldav_uid
    filter_args = ["caldav_uid.any:"]
    if args.project:
        filter_args.append(f"project:{args.project}")

    # Get matching tasks
    try:
        tasks = tw.export_tasks(filter_args)
        if not tasks:
            if args.project:
                logger.info(
                    f"No tasks with caldav_uid found in project '{args.project}'"
                )
            else:
                logger.info("No tasks with caldav_uid found")
            return 0

        logger.info(f"Found {len(tasks)} task(s) with caldav_uid")

        # Show tasks
        for task in tasks:
            project = task.project or "(no project)"
            description = task.description or "(no description)"
            caldav_uid = task.caldav_uid or ""
            print(f"  - [{project}] {description} (caldav_uid: {caldav_uid[:20]}...)")

        # Confirm unless --yes flag is provided
        if not args.yes and not args.dry_run:
            print()
            response = input("Remove caldav_uid from these tasks? [y/N]: ")
            if response.lower() not in ["y", "yes"]:
                logger.info("Unlink cancelled by user")
                return 0

        # Remove caldav_uid from each task
        if not args.dry_run:
            for task in tasks:
                task_id = task.uuid
                logger.debug(f"Removing caldav_uid from task {task_id}")
                tw.modify_task(task_id, {"caldav_uid": "", "caldav_base": ""})
            logger.info(f"Successfully unlinked {len(tasks)} task(s)")
        else:
            logger.info(f"Would unlink {len(tasks)} task(s)")

        return 0

    except Exception as e:
        logger.error(f"Failed to unlink tasks: {e}")
        logger.debug("Exception details:", exc_info=True)
        return 1


def cmd_test_caldav(args: argparse.Namespace) -> int:
    """Execute the test-caldav command.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    from .caldav_client import CalDAVClient
    from .config import Config
    from .logger import setup_logger

    # Setup logging
    logger = setup_logger(verbose=args.verbose)

    logger.info("Testing CalDAV connection")

    # Load configuration
    try:
        config = Config.from_file(args.config)
        logger.debug(f"Loaded configuration from {args.config or 'default location'}")
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    # Test CalDAV connection
    try:
        logger.debug(f"Connecting to {config.caldav.url}")
        caldav_client = CalDAVClient(
            url=config.caldav.url,
            username=config.caldav.username,
            password=config.caldav.password,
        )

        logger.info("Successfully connected to CalDAV server")
        print()
        print("CalDAV Connection Test Results:")
        print(f"  Server URL: {config.caldav.url}")
        print(f"  Username: {config.caldav.username}")
        print()

        # List available calendars
        logger.debug("Fetching available calendars")
        calendars = caldav_client.list_calendars()

        if calendars:
            print(f"Found {len(calendars)} calendar(s):")
            for cal_name in calendars:
                print(f"  - {cal_name}")
                # Check if calendar is mapped in config
                mapped_project = None
                for mapping in config.mappings:
                    if mapping.caldav_calendar == cal_name:
                        mapped_project = mapping.taskwarrior_project
                        break
                if mapped_project:
                    print(f"    Mapped to project: {mapped_project}")
            print()
        else:
            print("No calendars found")
            print()

        # Show configured mappings
        print("Configured project → calendar mappings:")
        for mapping in config.mappings:
            print(f"  {mapping.taskwarrior_project} → {mapping.caldav_calendar}")
        print()

        logger.info("CalDAV connection test completed successfully")
        return 0

    except Exception as e:
        logger.error(f"CalDAV connection test failed: {e}")
        logger.debug("Exception details:", exc_info=True)
        return 1


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the application.

    Args:
        argv: Command-line arguments. If None, uses sys.argv.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    args = parse_args(argv)

    # Route to appropriate command handler
    if args.command == "sync":
        return cmd_sync(args)
    if args.command == "unlink":
        return cmd_unlink(args)
    if args.command == "test-caldav":
        return cmd_test_caldav(args)
    # This shouldn't happen due to parse_args default, but handle it just in case
    print(
        "Error: No command specified. Use 'twcaldav sync' or see 'twcaldav --help'",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
