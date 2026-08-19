"""Unit tests for `core/run_log.py`: the ring buffer, live subscriber fan-out, sequence-number
de-duplication between a snapshot and its queue, and the closed/terminal signal (concept doc,
section C.7 Ausprägung (b) "WEB-Konsole").
"""

import asyncio

import pytest

from sentinel_fleet.core.run_log import MAX_RETAINED_LINES, RUN_CLOSED, RunLog, RunLogBus


# ---------------------------------------------------------------------------
# RunLog: one run's buffer plus its live subscribers.
# ---------------------------------------------------------------------------

def test_emit_appends_a_timestamped_line_and_returns_it():
    log = RunLog()
    returned = log.emit("step 1/1 started")
    lines, last_seq, closed = log.snapshot()
    assert lines == [returned]
    assert returned.endswith("step 1/1 started")
    assert last_seq == 1
    assert closed is False


def test_ring_buffer_keeps_only_the_most_recent_lines():
    log = RunLog()
    for i in range(MAX_RETAINED_LINES + 50):
        log.emit(f"line {i}")
    lines, last_seq, _ = log.snapshot()
    assert len(lines) == MAX_RETAINED_LINES
    # The oldest 50 were dropped; the buffer holds the tail, newest last.
    assert lines[0].endswith(f"line {50}")
    assert lines[-1].endswith(f"line {MAX_RETAINED_LINES + 49}")
    assert last_seq == MAX_RETAINED_LINES + 50


def test_close_marks_the_run_closed():
    log = RunLog()
    assert log.snapshot()[2] is False
    log.close()
    assert log.snapshot()[2] is True


@pytest.mark.asyncio
async def test_subscriber_receives_emitted_entries_with_increasing_sequence_numbers():
    """`emit()` wakes a subscriber via `call_soon_threadsafe`, which only schedules the
    delivery rather than performing it inline (see the cross-thread test below for why) - so
    the test awaits the queue instead of using `get_nowait()` right after `emit()`."""
    log = RunLog()
    queue = log.subscribe()
    log.emit("first")
    log.emit("second")

    seq1, line1 = await asyncio.wait_for(queue.get(), timeout=2)
    seq2, line2 = await asyncio.wait_for(queue.get(), timeout=2)
    assert (seq1, seq2) == (1, 2)
    assert line1.endswith("first")
    assert line2.endswith("second")


@pytest.mark.asyncio
async def test_close_wakes_every_live_subscriber_with_the_closed_sentinel():
    log = RunLog()
    queue_a = log.subscribe()
    queue_b = log.subscribe()
    log.close()

    assert await asyncio.wait_for(queue_a.get(), timeout=2) is RUN_CLOSED
    assert await asyncio.wait_for(queue_b.get(), timeout=2) is RUN_CLOSED


@pytest.mark.asyncio
async def test_unsubscribe_stops_further_delivery():
    log = RunLog()
    queue = log.subscribe()
    log.unsubscribe(queue)
    log.emit("nobody is listening")
    assert queue.empty()


@pytest.mark.asyncio
async def test_snapshot_and_subscribe_never_lose_or_duplicate_a_line():
    """The exact race the seq-number scheme exists for: subscribe, then read the snapshot -
    every entry already in the snapshot must be skippable from the queue via `seq > last_seq`,
    with nothing missed and nothing double-delivered, regardless of what already happened before
    subscribing."""
    log = RunLog()
    log.emit("before subscribe 1")
    log.emit("before subscribe 2")

    queue = log.subscribe()
    lines, last_seq, _ = log.snapshot()
    assert len(lines) == 2
    assert last_seq == 2

    log.emit("after subscribe 1")
    log.emit("after subscribe 2")

    delivered = []
    for _ in range(2):
        seq, line = await asyncio.wait_for(queue.get(), timeout=2)
        if seq > last_seq:
            delivered.append(line)

    assert len(delivered) == 2
    assert delivered[0].endswith("after subscribe 1")
    assert delivered[1].endswith("after subscribe 2")


@pytest.mark.asyncio
async def test_emit_wakes_a_subscriber_from_a_different_thread():
    """`emit()` must be safe to call from a thread other than the one running the subscriber's
    event loop (the real reason this needs `call_soon_threadsafe`, not just `put_nowait` -
    Starlette's TestClient runs the ASGI app on its own event-loop thread, and this is exactly
    that shape in miniature)."""
    log = RunLog()
    queue = log.subscribe()
    loop = asyncio.get_running_loop()

    def emit_from_other_thread():
        log.emit("cross-thread line")

    await loop.run_in_executor(None, emit_from_other_thread)
    seq, line = await asyncio.wait_for(queue.get(), timeout=2)
    assert seq == 1
    assert line.endswith("cross-thread line")


# ---------------------------------------------------------------------------
# RunLogBus: one RunLog per run_id, created lazily.
# ---------------------------------------------------------------------------

def test_bus_snapshot_of_an_unknown_run_is_empty_and_not_closed():
    bus = RunLogBus()
    assert bus.snapshot("no-such-run") == ([], 0, False)
    assert bus.is_closed("no-such-run") is False


def test_bus_creates_isolated_logs_per_run_id():
    bus = RunLogBus()
    bus.emit("run-a", "a line")
    bus.emit("run-b", "b line")

    lines_a, _, _ = bus.snapshot("run-a")
    lines_b, _, _ = bus.snapshot("run-b")
    assert lines_a[0].endswith("a line")
    assert lines_b[0].endswith("b line")


def test_bus_close_only_affects_the_named_run():
    bus = RunLogBus()
    bus.emit("run-a", "a")
    bus.emit("run-b", "b")
    bus.close("run-a")

    assert bus.is_closed("run-a") is True
    assert bus.is_closed("run-b") is False


def test_bus_close_of_an_unknown_run_does_not_raise():
    bus = RunLogBus()
    bus.close("never-emitted-to")  # must be a no-op, not an error
    assert bus.is_closed("never-emitted-to") is False
