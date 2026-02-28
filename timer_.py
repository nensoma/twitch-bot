"""Class for handling periodic bot operations."""
from __future__ import annotations
import time
from typing import Callable


class Timer:
    """
    Repeatedly run a function at a set interval.\n
    The function can be run independently of the timer
    by awaiting `Timer.timers[name]()`.
    """

    __slots__ = ["func", "interval", "last"]
    timers: dict[str, Timer] = {}

    def __init__(self, func: Callable, name: str, interval: int):
        self.func = func
        self.interval = interval
        self.last = time.perf_counter() - interval
        Timer.timers[name] = self

    async def __call__(self, *args, **kwargs):
        if time.perf_counter() - self.last >= self.interval:
            await self.func(*args, **kwargs)
            self.last = time.perf_counter()

    @classmethod
    def timer(cls, name: str, interval: int):
        """Instantiate a timer."""
        def wrapper(func):
            return cls(func, name, interval)
        return wrapper
