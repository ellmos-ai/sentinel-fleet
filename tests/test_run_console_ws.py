"""Tests for `/ws/run/{run_id}`, the run console's WebSocket endpoint (concept doc, section C.7
Ausprägung (b) "WEB-Konsole"). `run_id` is a `TaskRecord.task_id`.

Uses FastAPI's (synchronous) `TestClient`, not the `httpx.AsyncClient` fixture the rest of this
suite uses elsewhere - `websocket_connect()` needs it, and it runs the ASGI app on its own
event-loop thread, which is exactly why `run_log_bus.emit()` has to be safe to call from a
different thread than the one running the WebSocket handler (see `core/run_log.py` and
`tests/test_run_log.py::test_emit_wakes_a_subscriber_from_a_different_thread`).
"""

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from sentinel_fleet.core.run_log import run_log_bus
from sentinel_fleet.uas.task_master import TaskState, task_master
from sentinel_fleet.web.server import app

client = TestClient(app)


def _task(name="ws probe"):
    return task_master.create_task(name=name, assigned_agent="agent:task-solver", input_data={})


def test_unknown_run_id_is_rejected_before_the_handshake_completes():
    try:
        with client.websocket_connect("/ws/run/TASK-DOES-NOT-EXIST") as ws:
            ws.receive_text()
        assert False, "expected the connection to be denied"
    except WebSocketDisconnect as exc:
        assert exc.code == 4404


def test_a_terminal_run_replays_its_buffer_then_closes():
    task = _task()
    run_log_bus.emit(task.task_id, "line one")
    run_log_bus.emit(task.task_id, "line two")
    task_master.update_task_state(task.task_id, TaskState.IN_PROGRESS)
    task_master.update_task_state(task.task_id, TaskState.COMPLETED, output_data={})
    run_log_bus.close(task.task_id)

    with client.websocket_connect(f"/ws/run/{task.task_id}") as ws:
        assert ws.receive_text().endswith("line one")
        assert ws.receive_text().endswith("line two")
        # Replay-then-close is the honest common case: Phase 1 executes a run synchronously
        # inside the request that queued it, so a console opened afterwards has nothing left to
        # wait for (concept doc, section C.7 correction discussed with the advisor).
        try:
            ws.receive_text()
            assert False, "expected the socket to close after the replay"
        except WebSocketDisconnect as exc:
            assert exc.code == 1000


def test_a_task_state_marked_terminal_closes_the_socket_even_if_the_bus_was_never_closed():
    """Belt-and-braces guard: if some future emitter forgot to call `run_log_bus.close()`, the
    route still does not idle forever on a task whose own state is already terminal."""
    task = _task()
    run_log_bus.emit(task.task_id, "only line")
    task_master.update_task_state(task.task_id, TaskState.IN_PROGRESS)
    task_master.update_task_state(task.task_id, TaskState.FAILED, error="boom")
    # Deliberately NOT calling run_log_bus.close(task.task_id).

    with client.websocket_connect(f"/ws/run/{task.task_id}") as ws:
        assert ws.receive_text().endswith("only line")
        try:
            ws.receive_text()
            assert False, "expected the socket to close because the task state is terminal"
        except WebSocketDisconnect:
            pass


def test_a_historical_terminal_task_explains_that_no_durable_log_exists():
    task = _task("historical task")
    task_master.update_task_state(task.task_id, TaskState.IN_PROGRESS)
    task_master.update_task_state(task.task_id, TaskState.COMPLETED, output_data={})

    with client.websocket_connect(f"/ws/run/{task.task_id}") as ws:
        assert "predates persistent run logs" in ws.receive_text()


def test_a_queued_run_replays_then_streams_a_live_line_then_closes_on_run_log_bus_close():
    task = _task()
    run_log_bus.emit(task.task_id, "before connect")
    task_master.update_task_state(task.task_id, TaskState.IN_PROGRESS)

    with client.websocket_connect(f"/ws/run/{task.task_id}") as ws:
        assert ws.receive_text().endswith("before connect")

        # Emitted from the test's own thread while the WebSocket handler waits on a different
        # thread (TestClient's ASGI portal) - this is the exact scenario
        # call_soon_threadsafe exists for.
        run_log_bus.emit(task.task_id, "live line while connected")
        assert ws.receive_text().endswith("live line while connected")

        task_master.update_task_state(task.task_id, TaskState.COMPLETED, output_data={})
        run_log_bus.close(task.task_id)

        try:
            ws.receive_text()
            assert False, "expected the socket to close after run_log_bus.close()"
        except WebSocketDisconnect as exc:
            assert exc.code == 1000


def test_a_second_viewer_only_sees_lines_after_it_subscribed_plus_the_replay():
    """Two independent consoles on the same run: each gets its own subscriber queue, and
    connecting late does not lose the lines already emitted (they are in the buffer) or
    duplicate them (the seq-number guard in `core/run_log.py`)."""
    task = _task()
    run_log_bus.emit(task.task_id, "early line")
    task_master.update_task_state(task.task_id, TaskState.IN_PROGRESS)

    with client.websocket_connect(f"/ws/run/{task.task_id}") as first_viewer:
        assert first_viewer.receive_text().endswith("early line")

        with client.websocket_connect(f"/ws/run/{task.task_id}") as second_viewer:
            # The second viewer's replay also contains the early line - it was buffered.
            assert second_viewer.receive_text().endswith("early line")

            run_log_bus.emit(task.task_id, "seen by both")
            assert first_viewer.receive_text().endswith("seen by both")
            assert second_viewer.receive_text().endswith("seen by both")

        task_master.update_task_state(task.task_id, TaskState.COMPLETED, output_data={})
        run_log_bus.close(task.task_id)
        try:
            first_viewer.receive_text()
            assert False, "expected the remaining socket to close after run_log_bus.close()"
        except WebSocketDisconnect:
            pass
