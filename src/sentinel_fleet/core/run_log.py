"""Run-log bus: an in-memory, per-run ring buffer of human-readable log lines, plus a live
subscriber fan-out for the WebSocket console (concept doc, section C.7 "Consequence for Phase
3", variant (b), the web console).

This module has no knowledge of chains, templates, agents or the gateway. `chain_runner.py` and
`uas/routines.py` write plain strings into it at the exact points they already touch
`task_master`/`telemetry`; `/ws/run/{run_id}` (web/server.py) reads it back. A run's log line is
never model output content - only status/pattern/model/gate-verdict/error text - because this
bus feeds a WebSocket that has no auth of its own (concept doc: the console is a read-only view,
a security boundary, not just a scope boundary).

`run_id` is a `TaskRecord.task_id` throughout this module and its caller - there is no separate
"run" object here either, matching the concept doc's "no second object for one run"
(section A.2).
"""

import asyncio
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

# "Keep only last 1000 lines" - the same ring-buffer bound ellmos-filecommander-mcp uses for its
# own spawned-process console log (concept doc, section C.7). Reconnecting after this many lines
# only sees the tail, same trade-off that module already accepted.
MAX_RETAINED_LINES = 1000

# Sentinel pushed into every subscriber queue when a run closes. Never a `(seq, str)` tuple, so
# it can never collide with a real log entry and is always checked with `is`, not equality.
RUN_CLOSED = object()


class RunLog:
    """One run's line buffer plus whatever live subscribers are currently attached to it.

    Every line carries a monotonically increasing sequence number. A subscriber calls
    `subscribe()` and `snapshot()` back to back with no `await` in between (see the WebSocket
    route) - on a single-threaded event loop that pair is atomic, so the sequence number lets a
    subscriber that is handed both the buffered snapshot and a live queue discard whatever the
    queue re-delivers that the snapshot already covered, instead of the two racing each other.
    """

    def __init__(self):
        self._lines: Deque[Tuple[int, str]] = deque(maxlen=MAX_RETAINED_LINES)
        # Queue -> the event loop `subscribe()` was called from. `emit()` may be called from a
        # different thread than the one running a subscriber's WebSocket handler (this is
        # exercised by tests that drive the ASGI app through Starlette's TestClient, which runs
        # it on its own event-loop thread) - `asyncio.Queue.put_nowait` is only safe to call
        # from the loop that owns the queue, so every wakeup goes through
        # `call_soon_threadsafe`, which is safe from any thread, including the queue's own.
        self._subscribers: Dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}
        self._seq = 0
        self.closed = False

    def emit(self, line: str) -> str:
        self._seq += 1
        stamped = f"{time.strftime('%H:%M:%S')} {line}"
        entry = (self._seq, stamped)
        self._lines.append(entry)
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
        for queue, loop in list(self._subscribers.items()):
            loop.call_soon_threadsafe(queue.put_nowait, RUN_CLOSED)


class RunLogBus:
    """One `RunLog` per `run_id` (== `task_id`), created on first emit or subscribe. Never
    explicitly deleted - entries are cheap (a deque of at most 1000 short strings per run) and
    this is instance-local, in-memory state: a Cloud Run restart or a second instance behind the
    same URL neither sees nor needs to reclaim it, the same trade-off `task_master`'s own
    in-memory store already makes for this deployment's Phase 1 (concept doc, section B.2).
    """

    def __init__(self):
        self._runs: Dict[str, RunLog] = {}

    def _get_or_create(self, run_id: str) -> RunLog:
        run = self._runs.get(run_id)
        if run is None:
            run = RunLog()
            self._runs[run_id] = run
        return run

    def emit(self, run_id: str, line: str) -> str:
        return self._get_or_create(run_id).emit(line)

    def snapshot(self, run_id: str) -> Tuple[List[str], int, bool]:
        run = self._runs.get(run_id)
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


run_log_bus = RunLogBus()
