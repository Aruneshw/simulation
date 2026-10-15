"""Signal bus and transport primitives for the co-simulation coordinator."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Sample:
    value: Any
    t: float
    producer: str


class Bus:
    """Typed-by-convention signal store with zero-order hold semantics.

    A value stays valid until its producer writes a new one; consumers can
    check its age to detect stale data (e.g. a sensor that stopped publishing).
    """

    def __init__(self) -> None:
        self._s: dict[str, Sample] = {}

    def put(self, name: str, value: Any, t: float, producer: str) -> None:
        self._s[name] = Sample(value, t, producer)

    def get(self, name: str, default: Any = None) -> Any:
        s = self._s.get(name)
        return default if s is None else s.value

    def sample(self, name: str) -> Optional[Sample]:
        return self._s.get(name)

    def age(self, name: str, t: float) -> float:
        s = self._s.get(name)
        return float("inf") if s is None else t - s.t

    def names(self) -> list[str]:
        return sorted(self._s)


class DelayLine:
    """Fixed transport delay (communication latency) for a message stream."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.q: deque[tuple[float, Any]] = deque()
        self.out: Any = None

    def push(self, t: float, value: Any) -> None:
        self.q.append((t + self.delay, value))

    def pop(self, t: float) -> Any:
        while self.q and self.q[0][0] <= t + 1e-12:
            self.out = self.q.popleft()[1]
        return self.out
