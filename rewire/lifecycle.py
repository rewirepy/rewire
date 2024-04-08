from contextlib import asynccontextmanager
from anyio.abc._tasks import TaskGroup
from functools import partial
from inspect import iscoroutinefunction
import threading
from typing import (
    Any,
    AsyncContextManager,
    Awaitable,
    Callable,
    Coroutine,
    List,
    overload,
)
import anyio

from pydantic import PrivateAttr

from loguru import logger
from anyio.from_thread import run as run_async
from anyio.to_thread import run_sync

from rewire.space import Module, MultiAsyncContextManager

UNSET = object()
Callback = Callable[[], Any]


class LifecycleModule(Module):
    _stopEvent: threading.Event = PrivateAttr(default_factory=threading.Event)
    _stoppedEvent: threading.Event = PrivateAttr(default_factory=threading.Event)
    _lock: threading.RLock = PrivateAttr(default_factory=threading.RLock)
    _asyncStopEvent: anyio.Event = PrivateAttr(default_factory=anyio.Event)
    _coroutines: List[Any] = PrivateAttr(default_factory=list)
    _onStop: List[Callable] = PrivateAttr(default_factory=list)
    _running: dict[int, Awaitable | Callable] = PrivateAttr(default_factory=dict)
    _is_running: bool = PrivateAttr(False)
    _group: TaskGroup = PrivateAttr()
    _context_managers: list[AsyncContextManager] = PrivateAttr(default_factory=list)

    cancel_on_stop: bool = True
    stop_on_err: bool = True

    def run[T: Callable[[], Any] | Coroutine | Awaitable](self, target: T):
        """Start in non daemon thread if not async else run in main thread"""

        if not isinstance(target, Coroutine | Awaitable):
            cb = run_sync(partial(self.runner, target))  # type: ignore
        else:
            cb = target

        if self._is_running:
            self._group.start_soon(self.async_runner, cb)
        else:
            self._coroutines.append(cb)
        return target

    @property
    def running(self):
        return self._is_running

    @property
    def group(self):
        assert self.running
        return self._group

    async def start(self, run_stop: bool = True):
        async with self.use_running(False):
            logger.info("Running")
        if run_stop:
            await self.stop()

    @asynccontextmanager
    async def use_running(self, run_stop: bool = True):
        with self._lock:
            self._is_running = True

            logger.info("Starting...")
            self._stopEvent.clear()

        async with MultiAsyncContextManager(self._context_managers):
            async with anyio.create_task_group() as group:
                for coro in self._coroutines:
                    group.start_soon(self.async_runner, coro)

                self._group = group
                try:
                    yield
                finally:
                    if run_stop:
                        await self.stop()

    def runner(self, target: Callable[[], Any]):
        try:
            self._running[id(target)] = target
            target()
        except Exception as e:
            if self.stop_on_err:
                self.stop_sync()
                logger.opt(exception=True).critical(
                    "Stopping due to exception in runner"
                )
                raise e
        finally:
            del self._running[id(target)]

    async def async_runner(self, target: Awaitable):
        try:
            self._running[id(target)] = target
            await target
        except Exception as e:
            if self.stop_on_err:
                await self.stop()
                logger.opt(exception=True).critical(
                    "Stopping due to exception in runner"
                )
                raise e
        finally:
            del self._running[id(target)]

    @overload
    def on_stop[TC: Callback](self) -> Callable[[TC], TC]: ...

    @overload
    def on_stop[TC: Callback](self, cb: TC) -> TC: ...

    def on_stop[TC: Callback](self, cb: TC | Any = UNSET) -> TC | Callable[[TC], TC]:
        if cb is not UNSET:
            self._onStop.append(cb)
            return cb

        def wrapper(cb: TC) -> TC:
            self.on_stop(cb)
            return cb

        return wrapper

    def stop_sync(self):
        self._stoppedEvent.clear()
        run_async(self.stop)
        return self._stoppedEvent

    async def stop(self):
        if not self._is_running:
            return self._stoppedEvent
        logger.info("Stopping")
        self._is_running = False
        self._asyncStopEvent.set()
        with self._lock:
            if self._stopEvent.is_set():
                return self._stoppedEvent
            self._stopEvent.set()

        for cb in self._onStop:
            if iscoroutinefunction(cb):
                await cb()
                continue

            await run_sync(cb)

        self._stoppedEvent.set()
        if self.cancel_on_stop:
            self._group.cancel_scope.cancel()

        return self._stoppedEvent

    def contextmanager[T: AsyncContextManager](self, contextmanager: T):
        assert not self._running, "Unable to add contextmanager to running lifecycle"
        self._context_managers.append(contextmanager)
        return contextmanager
