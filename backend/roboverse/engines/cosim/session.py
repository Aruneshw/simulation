"""Live simulation sessions: a coordinator running in a worker thread with
pause/resume/stop/reset, speed control, E-stop and teleop, streaming frames to
any number of WebSocket subscribers through asyncio queues."""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Callable, Optional

from ...library.registry import Registry
from ...schemas.project import Project
from .coordinator import Coordinator


class SimSession:
    def __init__(self, run_id: str, project: Project, registry: Registry,
                 on_finish: Optional[Callable[["SimSession", dict], None]] = None):
        self.id = run_id
        self.project = project
        self.registry = registry
        self.on_finish = on_finish
        self.subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self.speed = project.simulation.real_time_factor
        self.status = "created"
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self._make()

    def _make(self):
        self.coord = Coordinator(self.project, self.registry, on_frame=self._broadcast)
        self.init_report = self.coord.initialize()
        self._clock = (time.perf_counter(), 0.0)

    # ------------------------------------------------------------ streaming --
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self.lock:
            self.subscribers.append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self.lock:
            self.subscribers = [(lp, x) for lp, x in self.subscribers if x is not q]

    def _broadcast(self, msg: dict) -> None:
        with self.lock:
            subs = list(self.subscribers)
        for loop, q in subs:
            def put(q=q, msg=msg):
                if q.full():
                    try:
                        q.get_nowait()  # drop oldest frame rather than block the simulation
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(msg)
            try:
                loop.call_soon_threadsafe(put)
            except RuntimeError:
                pass

    # -------------------------------------------------------------- control --
    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            self._pause.clear()
            return
        self._stop.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"sim-{self.id}")
        self.thread.start()

    def _reset_clock(self) -> None:
        """Re-anchor real-time pacing (after pause or a speed change)."""
        self._clock = (time.perf_counter(), self.coord.t)

    def _pace(self, t: float) -> None:
        while self._pause.is_set() and not self._stop.is_set():
            time.sleep(0.05)
            self._reset_clock()
        if self.speed > 0:
            delay = self._clock[0] + (t - self._clock[1]) / self.speed - time.perf_counter()
            if delay > 0:
                time.sleep(min(delay, 0.1))

    def _run(self) -> None:
        self.status = "running"
        self._broadcast({"type": "status", "status": "running", "init": self.init_report})
        try:
            self._reset_clock()
            res = self.coord.run(should_stop=self._stop.is_set, pace=self._pace)
            self.result = res
            self.status = res["status"]
        except Exception as e:  # noqa: BLE001
            self.status = "error"
            self.error = f"{type(e).__name__}: {e}"
            self.result = self.coord.results()
            self.result["status"] = "error"
        self._broadcast({"type": "finished", "status": self.status, "result": self.result, "error": self.error})
        if self.on_finish:
            self.on_finish(self, self.result)

    def pause(self) -> None:
        self._pause.set()
        self.status = "paused"
        self._broadcast({"type": "status", "status": "paused"})

    def resume(self) -> None:
        self._pause.clear()
        self._reset_clock()
        self.status = "running"
        self._broadcast({"type": "status", "status": "running"})

    def stop(self) -> None:
        self._stop.set()
        self._pause.clear()

    def reset(self) -> None:
        self.stop()
        if self.thread:
            self.thread.join(timeout=5)
        self._make()
        self.status = "created"
        self._broadcast({"type": "status", "status": "reset", "init": self.init_report})

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.0, float(speed))
        self._reset_clock()

    def estop(self, on: bool) -> None:
        self.coord.ctx.estop = on
        self.coord.ctx.event(self.coord.t, "estop", "Emergency stop " + ("ENGAGED by operator" if on else "released"),
                             "warning" if on else "info")

    def teleop(self, v: Optional[float], w: Optional[float]) -> None:
        self.coord.ctx.teleop_cmd = None if v is None else (float(v), float(w or 0.0))


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, SimSession] = {}

    def create(self, run_id: str, project: Project, registry: Registry, on_finish=None) -> SimSession:
        s = SimSession(run_id, project, registry, on_finish)
        self.sessions[run_id] = s
        return s

    def get(self, run_id: str) -> Optional[SimSession]:
        return self.sessions.get(run_id)


SESSIONS = SessionManager()
