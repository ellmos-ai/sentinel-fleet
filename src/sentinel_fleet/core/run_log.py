"""Run-log bus: a durable, bounded per-run replay plus live in-process subscriber fan-out for
the WebSocket console (concept doc, section C.7 "Consequence for Phase 3", variant (b)).

This module has no knowledge of chains, templates, agents or the gateway. `chain_runner.py` and
`uas/routines.py` write plain strings into it at the exact points they already touch
`task_master`/`telemetry`; `/ws/run/{run_id}` (web/server.py) reads it back. A run's log line is
never model output content - only status/pattern/model/gate-verdict/error text. The WebSocket is
read-only and uses the same demo/IAP boundary as the HTTP surface.

`run_id` is a `TaskRecord.task_id` throughout this module and its caller - there is no separate
"run" object here either, matching the concept doc's "no second object for one run"
(section A.2).
"""

import asyncio
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from sentinel_fleet.core.storage import BaseStore, get_store

# "Keep only last 1000 lines" - the same ring-buffer bound ellmos-filecommander-mcp uses for its
# own spawned-process console log (concept doc, section C.7). Reconnecting after this many lines
# only sees the tail, same trade-off that module already accepted.
MAX_RETAINED_LINES = 1000

# Sentinel pushed into every subscriber queue when a run closes. Never a `(seq, str)` tuple, so
# it can never collide with a real log entry and is always checked with `is`, not equality.
RUN_CLOSED = object()


class RunLogEntry(BaseModel):
    """One durable line in a run log."""

    sequence: int
    text: str


class RunLogRecord(BaseModel):
    """Persistent replay state for one TaskRecord.

    Live subscriber queues intentionally stay process-local.  The replay is durable so a task
    and its evidence have the same lifetime across Cloud Run cold starts.
    """

    run_id: str
    entries: List[RunLogEntry] = Field(default_factory=list)
    last_sequence: int = 0
    closed: bool = False
    updated_at: float = Field(default_factory=time.time)


class RunLog:
    """One run's line buffer plus whatever live subscribers are currently attached to it.

    Every line carries a monotonically increasing sequence number. A subscriber calls
    `subscribe()` and `snapshot()` back to back with no `await` in between (see the WebSocket
    route) - on a single-threaded event loop that pair is atomic, so the sequence number lets a
    subscriber that is handed both the buffered snapshot and a live queue discard whatever the
    queue re-delivers that the snapshot already covered, instead of the two racing each other.
    """

    def __init__(
        self,
        run_id: str = "",
        persisted: Optional[RunLogRecord] = None,
        persist: Optional[Callable[[RunLogRecord], None]] = None,
    ):
        self.run_id = run_id or (persisted.run_id if persisted else "")
        initial = (
            [(entry.sequence, entry.text) for entry in persisted.entries]
            if persisted else []
        )
        self._lines: Deque[Tuple[int, str]] = deque(initial, maxlen=MAX_RETAINED_LINES)
        # Queue -> the event loop `subscribe()` was called from. `emit()` may be called from a
        # different thread than the one running a subscriber's WebSocket handler (this is
        # exercised by tests that drive the ASGI app through Starlette's TestClient, which runs
        # it on its own event-loop thread) - `asyncio.Queue.put_nowait` is only safe to call
        # from the loop that owns the queue, so every wakeup goes through
        # `call_soon_threadsafe`, which is safe from any thread, including the queue's own.
        self._subscribers: Dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}
        self._seq = persisted.last_sequence if persisted else 0
        self.closed = persisted.closed if persisted else False
        self._persist_callback = persist

    def _persist(self) -> None:
        if self._persist_callback is None or not self.run_id:
            return
        self._persist_callback(RunLogRecord(
            run_id=self.run_id,
            entries=[RunLogEntry(sequence=seq, text=text) for seq, text in self._lines],
            last_sequence=self._seq,
            closed=self.closed,
            updated_at=time.time(),
        ))

    def emit(self, line: str) -> str:
        self._seq += 1
        stamped = f"{time.strftime('%H:%M:%S')} {line}"
        entry = (self._seq, stamped)
        self._lines.append(entry)
        self._persist()
        for queue, loop in list(self._subscribers.items()):
            loop.call_soon_threadsafe(queue.put_nowait, entry)
        return stamped

    def snapshot(self) -> Tuple[List[str], int, bool]:
        """The buffered lines, the sequence number of the last one, and whether the run has
        already closed - a fresh WebSocket connection uses all three: the lines to replay, the
        sequence number to de-duplicate against its live queue, and `closed` to decide whether
        there is anything left to wait for at all."""
        entries = list(self._lines)
        last_seq = entries[-1][0] if entries else 0
        return [line for _, line in entries], last_seq, self.closed

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[queue] = asyncio.get_running_loop()
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.pop(queue, None)

    def close(self) -> None:
        """Marks the run as finished and wakes every live subscriber with one `RUN_CLOSED`
        sentinel each, so a WebSocket handler can tell "another line" from "the run is over,
        stop waiting" without polling."""
        self.closed = True
        self._persist()
        for queue, loop in list(self._subscribers.items()):
            loop.call_soon_threadsafe(queue.put_nowait, RUN_CLOSED)


class RunLogBus:
    """One `RunLog` per `run_id` (== `task_id`), created on first emit or subscribe.

    Subscriber queues are live process state.  When a store is supplied, the bounded replay is
    written after every line and close transition, so another instance can reconstruct it.
    """

    def __init__(self, store: Optional[BaseStore[RunLogRecord]] = None):
        self._runs: Dict[str, RunLog] = {}
        self._store = store

    def _persist(self, record: RunLogRecord) -> None:
        if self._store is not None:
            self._store.put(record.run_id, record)

    def _get_or_create(self, run_id: str) -> RunLog:
        run = self._runs.get(run_id)
        if run is None:
            persisted = self._store.get(run_id) if self._store is not None else None
            run = RunLog(run_id=run_id, persisted=persisted, persist=self._persist)
            self._runs[run_id] = run
        return run

    def emit(self, run_id: str, line: str) -> str:
        return self._get_or_create(run_id).emit(line)

    def snapshot(self, run_id: str) -> Tuple[List[str], int, bool]:
        run = self._runs.get(run_id)
        if run is None and self._store is not None and self._store.get(run_id) is not None:
            run = self._get_or_create(run_id)
        return run.snapshot() if run is not None else ([], 0, False)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        return self._get_or_create(run_id).subscribe()

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        run = self._runs.get(run_id)
        if run is not None:
            run.unsubscribe(queue)

    def close(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run is not None:
            run.close()

    def is_closed(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        return run.closed if run is not None else False


run_log_bus = RunLogBus(store=get_store("run_logs", RunLogRecord))
