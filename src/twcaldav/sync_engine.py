"""Synchronization engine for TaskWarrior and CalDAV."""

from twcaldav.caldav_client import CalDAVClient, VTodo
from twcaldav.config import Config
from twcaldav.field_mapper import caldav_to_taskwarrior, taskwarrior_to_caldav
from twcaldav.logger import get_logger
from twcaldav.sync_classifier import SyncClassifier
from twcaldav.sync_comparator import TaskComparator
from twcaldav.sync_types import SyncAction, SyncDirection, SyncStats, TaskPair
from twcaldav.taskwarrior import Task, TaskWarrior


class SyncEngine:
    """Synchronization engine for TaskWarrior and CalDAV."""

    def __init__(
        self,
        config: Config,
        tw: TaskWarrior,
        caldav_client: CalDAVClient,
        dry_run: bool = False,
    ) -> None:
        """Initialize sync engine.

        Args:
            config: Configuration object.
            tw: TaskWarrior client.
            caldav_client: CalDAV client.
            dry_run: If True, don't make any changes.
        """
        self.config = config
        self.tw = tw
        self.caldav = caldav_client
        self.dry_run = dry_run
        self.logger = get_logger()
        self.stats = SyncStats()
        self.caldav_uid_to_calendar: dict[
            str, str
        ] = {}  # Maps CalDAV UID to calendar ID

        # Initialize helpers
        self.comparator = TaskComparator()
        self.classifier = SyncClassifier(config, self.comparator)

    def sync(self) -> SyncStats:
        """Perform bi-directional synchronization.

        Returns:
            Sync statistics.
        """
        self.logger.info("Starting synchronization...")
        if self.dry_run:
            self.logger.info("DRY RUN MODE: No changes will be made")

        try:
            # Discovery phase
            task_pairs = self._discover_and_correlate()

            # Log sync plan summary
            self._log_sync_plan(task_pairs)

            # Classify and execute sync actions
            for pair in task_pairs:
                self._execute_sync_action(pair)

            self.logger.info("Synchronization complete")
            self.logger.info(str(self.stats))

        except Exception as e:
            self.logger.error(f"Sync failed: {e}")
            self.stats.errors += 1
            raise

        return self.stats

    def _discover_and_correlate(self) -> list[TaskPair]:
        """Discover tasks and correlate them between TaskWarrior and CalDAV.

        Returns:
            List of task pairs with sync actions.
        """
        self.logger.debug("Discovering tasks...")

        # Collect all tasks from TaskWarrior in mapped projects
        tw_tasks: dict[str, Task] = {}
        caldav_uid_to_tw_task: dict[str, Task] = {}  # Map CalDAV UID to TW task

        for mapping in self.config.mappings:
            project = mapping.taskwarrior_project
            self.logger.debug(f"Loading TaskWarrior tasks from project: {project}")

            # Export all tasks for this project (all statuses including deleted)
            # We need deleted tasks to detect deletions and sync them to CalDAV
            tasks = self.tw.export_tasks(project=project)
            for task in tasks:
                tw_tasks[task.uuid] = task
                # Build mapping from CalDAV UID to TW task (including deleted ones)
                if task.caldav_uid:
                    caldav_uid_to_tw_task[task.caldav_uid] = task

        # Count tasks by status for clearer logging
        deleted_without_caldav = sum(
            1 for t in tw_tasks.values() if t.status == "deleted" and not t.caldav_uid
        )
        active_count = len(tw_tasks) - deleted_without_caldav

        if deleted_without_caldav > 0:
            self.logger.info(
                f"Found {len(tw_tasks)} TaskWarrior tasks in mapped projects "
                f"({active_count} active, {deleted_without_caldav} deleted "
                f"without CalDAV link)"
            )
        else:
            self.logger.info(
                f"Found {len(tw_tasks)} TaskWarrior tasks in mapped projects"
            )

        # Collect all VTODOs from CalDAV in mapped calendars
        caldav_todos: dict[str, VTodo] = {}
        caldav_uid_to_calendar: dict[str, str] = {}  # Map CalDAV UID to calendar ID

        for mapping in self.config.mappings:
            calendar_id = mapping.caldav_calendar
            self.logger.debug(f"Loading CalDAV todos from calendar ID: {calendar_id}")
            todos = self.caldav.get_todos(calendar_id)

            for todo in todos:
                caldav_todos[todo.uid] = todo
                caldav_uid_to_calendar[todo.uid] = (
                    calendar_id  # Store which calendar this todo is from
                )

        self.logger.info(f"Found {len(caldav_todos)} CalDAV todos in mapped calendars")

        # Store calendar mapping for later use
        self.caldav_uid_to_calendar = caldav_uid_to_calendar

        # Correlate tasks and classify actions
        task_pairs = []

        # Process TaskWarrior tasks
        processed_caldav_uids: set[str] = set()
        for _tw_uuid, tw_task in tw_tasks.items():
            # Look for corresponding CalDAV todo via UDA
            caldav_todo = None
            if tw_task.caldav_uid:
                caldav_todo = caldav_todos.get(tw_task.caldav_uid)
                if caldav_todo:
                    processed_caldav_uids.add(caldav_todo.uid)

            pair = self.classifier.classify(tw_task, caldav_todo)
            task_pairs.append(pair)

        # Process CalDAV todos that don't have TaskWarrior counterparts
        for caldav_uid, caldav_todo in caldav_todos.items():
            # Skip if already processed via TaskWarrior UDA
            if caldav_uid in processed_caldav_uids:
                continue

            # Check if there's a TaskWarrior task that references this CalDAV UID
            # This handles the case where CalDAV todo exists but wasn't found in the
            # first loop
            tw_task = caldav_uid_to_tw_task.get(caldav_uid)
            if tw_task:
                # Found correlation - this CalDAV todo belongs to a TaskWarrior task
                pair = self.classifier.classify(tw_task, caldav_todo)
            else:
                # No TaskWarrior task references this CalDAV todo
                pair = self.classifier.classify(None, caldav_todo)
            task_pairs.append(pair)

        return task_pairs

    def _log_sync_plan(self, task_pairs: list[TaskPair]) -> None:
        """Log a summary of planned sync actions.

        Args:
            task_pairs: List of classified task pairs.
        """
        # Count actions by type
        create_count = sum(1 for p in task_pairs if p.action == SyncAction.CREATE)
        update_count = sum(1 for p in task_pairs if p.action == SyncAction.UPDATE)
        delete_count = sum(1 for p in task_pairs if p.action == SyncAction.DELETE)
        skip_count = sum(1 for p in task_pairs if p.action == SyncAction.SKIP)

        # Count skip reasons for more detail
        skip_reasons: dict[str, int] = {}
        for pair in task_pairs:
            if pair.action == SyncAction.SKIP:
                reason = pair.reason
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

        # Build sync plan message
        plan_parts = []
        if create_count > 0:
            plan_parts.append(f"{create_count} create")
        if update_count > 0:
            plan_parts.append(f"{update_count} update")
        if delete_count > 0:
            plan_parts.append(f"{delete_count} delete")
        if skip_count > 0:
            plan_parts.append(f"{skip_count} skip")

        if plan_parts:
            self.logger.info(f"Sync plan: {', '.join(plan_parts)}")

        # Log skip reason breakdown at debug level
        if skip_reasons:
            for reason, count in sorted(skip_reasons.items()):
                self.logger.debug(f"  Skip reason: {reason} ({count})")

    def _execute_sync_action(self, pair: TaskPair) -> None:
        """Execute the sync action for a task pair.

        Args:
            pair: Task pair with classified action.
        """
        if pair.action == SyncAction.SKIP:
            self.logger.debug(
                f"Skipping: {pair.reason} - "
                f"TW:{pair.tw_task.uuid if pair.tw_task else 'None'} / "
                f"CD:{pair.caldav_todo.uid if pair.caldav_todo else 'None'}"
            )
            self.stats.skipped += 1
            return

        try:
            if pair.action == SyncAction.CREATE:
                self._execute_create(pair)
            elif pair.action == SyncAction.UPDATE:
                self._execute_update(pair)
            elif pair.action == SyncAction.DELETE:
                self._execute_delete(pair)

        except Exception as e:
            self.logger.error(
                f"Error executing {pair.action.value} for "
                f"TW:{pair.tw_task.uuid if pair.tw_task else 'None'} / "
                f"CD:{pair.caldav_todo.uid if pair.caldav_todo else 'None'}: {e}"
            )
            self.stats.errors += 1

    def _execute_create(self, pair: TaskPair) -> None:
        """Execute create action.

        Args:
            pair: Task pair with CREATE action.
        """
        if pair.direction == SyncDirection.TW_TO_CALDAV:
            assert pair.tw_task is not None
            self.logger.info(
                f"Creating CalDAV todo from TaskWarrior task: {pair.tw_task.uuid}"
            )

            if not self.dry_run:
                # Convert TaskWarrior task to CalDAV todo
                vtodo = taskwarrior_to_caldav(pair.tw_task)

                # Get the calendar for this task's project
                calendar_name = self.config.get_calendar_for_project(
                    pair.tw_task.project or ""
                )
                if not calendar_name:
                    self.logger.warning(
                        f"No calendar mapping for project: {pair.tw_task.project}"
                    )
                    self.stats.skipped += 1
                    return

                self.caldav.create_todo(calendar_name, vtodo)

                # Update TaskWarrior task with CalDAV UID
                self.tw.modify_task(pair.tw_task.uuid, {"caldav_uid": vtodo.uid})
                self.logger.debug(
                    f"Set caldav_uid UDA to {vtodo.uid} on task {pair.tw_task.uuid}"
                )

            self.stats.caldav_created += 1

        elif pair.direction == SyncDirection.CALDAV_TO_TW:
            assert pair.caldav_todo is not None
            self.logger.info(
                f"Creating TaskWarrior task from CalDAV todo: {pair.caldav_todo.uid}"
            )

            if not self.dry_run:
                # Convert CalDAV todo to TaskWarrior task
                task = caldav_to_taskwarrior(pair.caldav_todo)

                # Set the project based on which calendar this todo came from
                calendar_id = self.caldav_uid_to_calendar.get(pair.caldav_todo.uid)
                if calendar_id:
                    project = self.config.get_project_for_calendar(calendar_id)
                    if project:
                        task.project = project

                self.tw.create_task(task)

            self.stats.tw_created += 1

    def _execute_update(self, pair: TaskPair) -> None:
        """Execute update action.

        Args:
            pair: Task pair with UPDATE action.
        """
        assert pair.tw_task is not None and pair.caldav_todo is not None

        if pair.direction == SyncDirection.TW_TO_CALDAV:
            # Check if this is a "set CANCELLED" update (TW deleted, delete_tasks=false)
            if pair.tw_task.status == "deleted":
                self._execute_cancel_caldav(pair)
                return

            self.logger.info(
                f"Updating CalDAV todo from TaskWarrior: {pair.tw_task.uuid}"
            )

            if not self.dry_run:
                # Convert TaskWarrior task to CalDAV todo (preserving UID and
                # any note already on the CalDAV side)
                vtodo = taskwarrior_to_caldav(
                    pair.tw_task, existing_description=pair.caldav_todo.description
                )
                vtodo.uid = pair.caldav_todo.uid  # Preserve CalDAV UID

                # Get the calendar
                calendar_name = self.config.get_calendar_for_project(
                    pair.tw_task.project or ""
                )
                if not calendar_name:
                    self.logger.warning(
                        f"No calendar mapping for project: {pair.tw_task.project}"
                    )
                    self.stats.skipped += 1
                    return

                self.caldav.update_todo(calendar_name, vtodo)

            self.stats.caldav_updated += 1

        elif pair.direction == SyncDirection.CALDAV_TO_TW:
            self.logger.info(
                f"Updating TaskWarrior task from CalDAV: {pair.caldav_todo.uid}"
            )

            if not self.dry_run:
                # Convert CalDAV todo to TaskWarrior task (preserving UUID)
                # Pass existing task to enable annotation deduplication
                task = caldav_to_taskwarrior(
                    pair.caldav_todo, existing_task=pair.tw_task
                )
                task.uuid = pair.tw_task.uuid  # Preserve TaskWarrior UUID
                task.entry = pair.tw_task.entry  # Preserve entry timestamp

                # Set the project based on which calendar this todo came from
                calendar_id = self.caldav_uid_to_calendar.get(pair.caldav_todo.uid)
                if calendar_id:
                    project = self.config.get_project_for_calendar(calendar_id)
                    if project:
                        task.project = project

                # Ensure caldav_uid is set
                if not task.caldav_uid:
                    task.caldav_uid = pair.caldav_todo.uid

                # Use import_tasks to update - this properly handles all fields
                # including annotations, unlike modify_task
                self.tw.import_tasks([task])

            self.stats.tw_updated += 1

    def _execute_cancel_caldav(self, pair: TaskPair) -> None:
        """Execute cancel action on CalDAV todo (soft delete).

        Called when TW task is deleted but delete_tasks=false.
        Sets CalDAV todo status to CANCELLED instead of deleting it.

        Args:
            pair: Task pair with UPDATE action (TW deleted → CalDAV CANCELLED).
        """
        assert pair.tw_task is not None and pair.caldav_todo is not None

        self.logger.info(
            f"Cancelling CalDAV todo (TaskWarrior task deleted): {pair.caldav_todo.uid}"
        )

        if not self.dry_run:
            # Get the calendar
            calendar_name = self.config.get_calendar_for_project(
                pair.tw_task.project or ""
            )
            if not calendar_name:
                self.logger.warning(
                    f"No calendar mapping for project: {pair.tw_task.project}"
                )
                self.stats.skipped += 1
                return

            self.caldav.cancel_todo(calendar_name, pair.caldav_todo.uid)

        self.stats.caldav_updated += 1

    def _execute_delete(self, pair: TaskPair) -> None:
        """Execute delete action.

        Args:
            pair: Task pair with DELETE action.
        """
        assert pair.tw_task is not None  # TW task must always exist for DELETE

        if pair.direction == SyncDirection.TW_TO_CALDAV:
            assert (
                pair.caldav_todo is not None
            )  # CalDAV todo must exist for TW→CalDAV delete
            self.logger.info(
                f"Deleting CalDAV todo (TaskWarrior task deleted): "
                f"{pair.caldav_todo.uid}"
            )

            if not self.dry_run:
                # Get the calendar
                calendar_name = self.config.get_calendar_for_project(
                    pair.tw_task.project or ""
                )
                if not calendar_name:
                    self.logger.warning(
                        f"No calendar mapping for project: {pair.tw_task.project}"
                    )
                    self.stats.skipped += 1
                    return

                self.caldav.delete_todo(calendar_name, pair.caldav_todo.uid)

            self.stats.caldav_deleted += 1

        elif pair.direction == SyncDirection.CALDAV_TO_TW:
            # CalDAV todo may be None if it was deleted externally (not just cancelled)
            caldav_info = (
                f" (caldav_uid: {pair.tw_task.caldav_uid})"
                if pair.tw_task.caldav_uid
                else ""
            )
            self.logger.info(
                f"Deleting TaskWarrior task (CalDAV todo deleted){caldav_info}: "
                f"{pair.tw_task.uuid}"
            )

            if not self.dry_run:
                self.tw.delete_task(pair.tw_task.uuid)

            self.stats.tw_deleted += 1
