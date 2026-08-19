"""TaskMaster: Asynchronous Task Engine & Execution State Table."""

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sentinel_fleet.core.storage import get_store
from sentinel_fleet.core.errors import TaskNotFoundError, TaskStateTransitionError


class TaskState(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    # A task the operator called off before it ran. Its own state rather than FAILED with a
    # reason: nothing went wrong, somebody decided, and a queue that cannot tell those two apart
    # reports every abandoned duplicate as a defect.
    CANCELLED = "cancelled"


# Terminal states have no outgoing edges: a completed, failed or cancelled task must never be
# resurrected. IN_PROGRESS deliberately cannot be cancelled - a run here is synchronous and over
# in seconds, so a cancel button on it would offer control that does not exist.
ALLOWED_TASK_TRANSITIONS: Dict[TaskState, set] = {
    TaskState.QUEUED: {
        TaskState.IN_PROGRESS, TaskState.AWAITING_APPROVAL, TaskState.COMPLETED,
        TaskState.FAILED, TaskState.CANCELLED,
    },
    TaskState.IN_PROGRESS: {TaskState.AWAITING_APPROVAL, TaskState.COMPLETED, TaskState.FAILED},
    TaskState.AWAITING_APPROVAL: {
        TaskState.IN_PROGRESS, TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED,
    },
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
}

TERMINAL_TASK_STATES = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}


class TaskRecord(BaseModel):
    task_id: str
    name: str
    assigned_agent: str
    state: TaskState = TaskState.QUEUED
    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_data: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    error_message: Optional[str] = None
    # Origin of a run created by the task-templates/routines feature. All four are optional
    # with a default, so a manually queued task (the pre-existing path) is unaffected. This is
    # the "view copy" the templates UI reads instead of a second, parallel run table: a run IS
    # a TaskRecord, just one that carries where it came from.
    source_template_id: Optional[str] = None
    source_binding_id: Optional[str] = None
    triggered_by: str = "manual"  # "manual" | "routine" | "schedule" | "external"
    scheduled_for: Optional[str] = None


class TaskMaster:
    def __init__(self):
        self._store = get_store("tasks", TaskRecord)

    def create_task(
        self,
        name: str,
        assigned_agent: str,
        input_data: Dict[str, Any],
        source_template_id: Optional[str] = None,
        source_binding_id: Optional[str] = None,
        triggered_by: str = "manual",
        scheduled_for: Optional[str] = None
    ) -> TaskRecord:
        # Collision-free: a counter over a shared store races and repeats ids after deletions
        task_id = f"TASK-{uuid.uuid4().hex[:8].upper()}"
        task = TaskRecord(
            task_id=task_id,
            name=name,
            assigned_agent=assigned_agent,
            state=TaskState.QUEUED,
            input_data=input_data,
            source_template_id=source_template_id,
            source_binding_id=source_binding_id,
            triggered_by=triggered_by,
            scheduled_for=scheduled_for
        )
        self._store.put(task_id, task)
        return task

    def list_by_template(self, template_id: str) -> List[TaskRecord]:
        """The run history ("Verlauf") of one template - newest first, no second store."""
        runs = [t for t in self._store.list_all() if t.source_template_id == template_id]
        runs.sort(key=lambda t: t.created_at, reverse=True)
        return runs

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self._store.get(task_id)

    def update_task_state(
        self,
        task_id: str,
        state: TaskState,
        output_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> TaskRecord:
        task = self._store.get(task_id)
        if not task:
            raise TaskNotFoundError(task_id)

        if state != task.state and state not in ALLOWED_TASK_TRANSITIONS.get(task.state, set()):
            raise TaskStateTransitionError(task_id, task.state.value, state.value)

        task.state = state
        task.updated_at = time.time()
        if output_data:
            task.output_data = output_data
        if error:
            task.error_message = error

        self._store.put(task_id, task)
        return task

    def cancel_task(self, task_id: str, reason: str = "Cancelled by the operator") -> TaskRecord:
        """Call off a task that has not run. Cancelling is a state, not an eraser.

        The record stays in the queue with its history intact; only its own outcome changes.
        Anything already settled, and anything currently running, is refused by the state
        machine rather than special-cased here.
        """
        task = self._store.get(task_id)
        if not task:
            raise TaskNotFoundError(task_id)
        return self.update_task_state(task_id, TaskState.CANCELLED, error=reason)

    def delete_task(self, task_id: str) -> bool:
        """Remove a settled record entirely - the one operation that does erase.

        Only a terminal task may go: deleting one that is still queued or running would drop
        work the fleet still owns, and the queue would stop matching what the fleet is doing.
        """
        task = self._store.get(task_id)
        if not task:
            raise TaskNotFoundError(task_id)
        if task.state not in TERMINAL_TASK_STATES:
            raise TaskStateTransitionError(task_id, task.state.value, "deleted")
        return self._store.delete(task_id)

    def list_all(self) -> List[TaskRecord]:
        tasks = self._store.list_all()
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks


task_master = TaskMaster()
