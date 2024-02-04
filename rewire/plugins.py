from contextlib import suppress
from functools import partial, wraps
import inspect
import os
from pathlib import Path
from typing import Awaitable, Callable, ClassVar

from anyio.to_thread import run_sync
from pydantic import BaseModel
from rewire.config import parse_file

from rewire.dependencies import (
    AnyRef,
    Dependencies,
    DependenciesModule,
    Dependency,
    InjectedDependency,
)
from rewire.lifecycle import LifecycleModule
from rewire.loader import LoaderModule
from rewire.space import Module

root_dir = os.getcwd()


class PluginConfig(BaseModel):
    requirements: list[str] = []
    include: list[str] = []


def to_async[T, **P](cb: Callable[P, Awaitable[T] | T]) -> Callable[P, Awaitable[T]]:
    if not inspect.iscoroutinefunction(cb):
        source = cb

        @wraps(cb)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await run_sync(partial(source, *args, **kwargs))  # type: ignore

        return wrapper

    return cb


class StageStart(Dependency):
    idx: int

    def _link(self):
        ends = [x for x in self.dependencies if isinstance(x, StageEnd)]
        ends.sort(key=lambda x: x.idx, reverse=True)
        self.dependencies = [
            x for x in self.dependencies if not isinstance(x, StageEnd)
        ] + ends[:1]
        return super()._link()


class StageEnd(Dependency):
    idx: int

    def _link(self):
        deps = Dependencies.ctx.get().all()
        for dep in deps:
            for sub in dep.dependencies:
                if isinstance(sub, StageStart) and sub.idx == self.idx:
                    self._dependencies.append(dep)
                    break
        super()._link()


class StagesModule(Dependencies, Module):
    stages: dict[int, tuple[StageStart, StageEnd]] = {}

    def get_stage(self, index: int):
        stages = StagesModule.get()
        if index in self.stages:
            return self.stages[index][0]
        start, end = (
            StageStart(priority=-1000, idx=index, label=f"StageStart@{index}"),
            StageEnd(priority=-1000, idx=index, label=f"StageEnd@{index}"),
        )
        for i, (stage_start, stage_end) in self.stages.items():
            if i < index:
                start.dependencies.append(stage_end)
            else:
                stage_start.dependencies.append(end)
        self.stages[index] = start, end
        stages.bind(start)
        stages.bind(end)
        return start


class Plugin(Dependencies):
    _stages: ClassVar[dict[int, tuple[StageStart, StageEnd]]] = {}
    name: str
    loc: Path | None = None
    conditions: list[str] = []

    def setup(
        self,
        priority: int = 0,
        stage: int | None = 0,
        dependencies: list[AnyRef] = [],
        inject_all: bool = True,
    ):
        def wrapper[T, **P](
            cb: Callable[P, Awaitable[T] | T],
        ) -> InjectedDependency[T, P]:
            cb = to_async(cb)
            dep = InjectedDependency.from_function(cb, all=inject_all)
            dep.priority = priority
            dep.dependencies.extend(dependencies)
            self.bind(dep)
            if stage is not None:
                with suppress(LookupError):
                    start = StagesModule.get().get_stage(stage)
                    dep.dependencies.append(start)

            return dep

        return wrapper

    def run(self):
        def wrapper[T, **P](
            cb: Callable[P, Awaitable[T] | T],
        ) -> InjectedDependency[None, P]:
            cb = to_async(cb)

            @wraps(cb)
            async def wrapped(*args: P.args, **kwargs: P.kwargs):
                lm = LifecycleModule.get()
                lm.run(cb(*args, **kwargs))

            return self.setup()(wrapped)

        return wrapper

    def config(self):
        return PluginConfig.model_validate(parse_file(self.config_path(), True))

    def location(self):
        if self.loc:
            return self.loc
        if self.name == ".":
            return Path(root_dir)
        return Path(root_dir, *self.name.split("."))

    def short_name(self):
        return self.name.split(".")[-1]

    def config_path(self):
        if self.location().is_dir():
            return self.location() / ".plugin.yaml"

        return self.location().parent / f"{self.short_name()}.plugin.yaml"


def simple_plugin(
    name: str | None = None,
    load: bool = True,
    bind: bool = True,
    loc: Path | None = None,
):
    if not name:
        name = "unknown"
        for i in range(1, 10):
            try:
                name = inspect.stack()[i][0].f_globals["__name__"]
                loc = inspect.stack()[i][0].f_globals["__file__"]
                break
            except KeyError:
                continue
    assert isinstance(name, str)

    plugin = Plugin(name=name, loc=loc)
    with suppress(LookupError):
        plugin.children.append(StagesModule.get())
        plugin.conditions.append("stages")
    with suppress(LookupError):
        if bind:
            DependenciesModule.get().add(plugin)
            plugin.conditions.append("dependencies")
    if load:
        config = plugin.config()

        with suppress(LookupError):
            loader = LoaderModule.get()
            plugin.conditions.append("loader")
            for item in config.include:
                loader.add(f"{plugin.name}.{item}")

    return plugin
