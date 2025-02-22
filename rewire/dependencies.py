from contextlib import asynccontextmanager
from functools import reduce, update_wrapper
import inspect
from typing import (
    Annotated,
    Any,
    Awaitable,
    Callable,
    Literal,
    Protocol,
    Self,
    Type,
    get_args,
    get_origin,
    get_type_hints,
)
from uuid import UUID, uuid4
from anyio import Event, create_task_group
from loguru import logger
from pydantic import BaseModel, Field, PrivateAttr

from rewire.context import CTX
from rewire.space import Module


async def noop(): ...


class SolveError(RuntimeError):
    pass


class DependencyNotFound(SolveError):
    pass


class SkipDependency(RuntimeError):
    pass


class DependencyRef(BaseModel):
    id: UUID
    label: str | None = None

    def resolve(self, deps: "Dependencies"):
        if self.id not in deps._by_id:
            raise DependencyNotFound(self.label or self.id)
        return deps._by_id[self.id]


class TypeRef(BaseModel):
    type: Any
    label: str | None = None

    def resolve(self, deps: "Dependencies"):
        if self.type not in deps._by_type:
            raise DependencyNotFound(self.label or self.type)
        return deps._by_type[self.type]


AnyRef = TypeRef | DependencyRef


class InjectMarker(BaseModel): ...


class Dependency[T](DependencyRef):
    id: UUID = Field(default_factory=uuid4)
    state: Literal["pending", "linked", "waiting", "running", "done", "skipped"] = (
        "pending"
    )
    # type of this dependency. (for by type injection)
    type: Any = None
    # a flag indicating whether this dependency creates a new type or just wraps an existing one.
    type_constructor: bool = True
    # the callback function that runs this dependency.
    cb: Callable[[], Awaitable[T]] = noop  # type: ignore
    # list of dependencies that are required to run before executing this dependency.
    dependencies: list[DependencyRef | TypeRef] = []
    # lower numbers run first.
    priority: int = 0
    # skip running this dependency instead of raising an exception when unable to resolve dependencies.
    optional: bool = False

    _event: Event | None = PrivateAttr(None)
    _dependencies: list["Dependency"] = PrivateAttr(default_factory=list)
    _result: T = PrivateAttr()

    ctx = CTX()

    def _link(self):
        deps = Dependencies.ctx.get()
        for dependency in self.dependencies:
            self._dependencies.append(dependency.resolve(deps))

    def link(self):
        if self.state != "pending":
            return
        try:
            self._link()
        except DependencyNotFound:
            if self.optional:
                raise SkipDependency()
            raise

        deps = Dependencies.ctx.get()
        deps._by_type[self.type] = self

        self.state = "linked"

    async def _run(self):
        return await self.cb()

    async def run(self):
        if self.state == "done":
            return self._result

        assert self.state == "linked"
        self.state = "waiting"

        for dep in self._dependencies:
            await dep.event.wait()

        self.state = "running"
        logger.trace(f"Running {self.pretty()}")
        with self.ctx.use():
            self._result = await self._run()
        logger.trace(f"Done {self.pretty()}")

        self.state = "done"
        self.event.set()
        return self._result

    @property
    def event(self):
        if self._event is None:
            self._event = Event()

        return self._event

    @property
    def Result(self) -> Type[T]:
        return Annotated[self.type, self]

    def pretty(self):
        return self.label or f"{type(self)} ({self.id})"

    def __dependency__(self):
        return self


class Dependable[T](Protocol):
    __dependency__: Callable[[], Dependency[T]]


class InjectedDependency[T, **P](Dependency[T]):
    cb: Callable[P, Awaitable[T]] = noop  # type: ignore
    map: dict[str, int] = {}

    async def __call__(self, *args: P.args, **kwds: P.kwargs) -> T:
        return await self.cb(*args, **kwds)

    async def _run(self):
        kw = {name: self._dependencies[idx]._result for name, idx in self.map.items()}
        return await self.cb(**kw)  # type: ignore

    @classmethod
    def from_function(  # /NOSONAR
        cls, cb: Callable[P, Awaitable[T]], all: bool = False
    ):
        self = cls(cb=cb, label=f"{cb.__module__}${cb.__name__}")
        sig = inspect.signature(cb)
        hints = get_type_hints(cb)
        if "return" in hints:
            self.type = hints["return"]
        hints_with_extra = get_type_hints(cb, include_extras=True)

        for name, param in sig.parameters.items():
            ref = None
            if (
                name in hints_with_extra
                and get_origin(hints_with_extra[name]) == Annotated
            ):
                for arg in get_args(hints_with_extra[name]):
                    if isinstance(arg, TypeRef | DependencyRef):
                        ref = arg
                        break
                    elif isinstance(arg, InjectMarker):
                        ref = TypeRef(type=hints[name], label=f"{self.label}/{name}")
                        break

            if name in hints and all and ref is None:
                ref = TypeRef(type=hints[name])
            elif ref is None:
                continue
            self.map[name] = len(self.dependencies)
            self.dependencies.append(ref)
            self.type_constructor = (
                self.type_constructor
                and isinstance(ref, TypeRef)
                and ref.type != self.type
            )
        update_wrapper(self, cb)
        return self

    @classmethod
    def inject_all_into(cls, cb: Callable[P, Awaitable[T]]):
        return cls.from_function(cb, all=True)

    @classmethod
    def inject_into(cls, cb: Callable[P, Awaitable[T]]):
        return cls.from_function(cb)


class Dependencies(BaseModel):
    ctx = CTX()
    dependencies: list[Dependency] = []
    children: list["Dependencies"] = []
    replace: list[tuple[AnyRef, Dependency]] = []
    linkers: list[Callable[[Self], Any]] = []
    _by_id: dict[UUID, Dependency] = PrivateAttr(default_factory=dict)
    _by_type: dict[Any, Dependency] = PrivateAttr(default_factory=dict)

    def all(self, ignore: set[UUID] = set()):
        deps = reduce(lambda a, b: a + b.all(ignore), self.children, self.dependencies)
        result: list[Dependency] = []
        visited = set()

        for dep in deps:
            if dep.id in visited or dep.id in ignore:
                continue
            visited.add(dep.id)
            result.append(dep)
        return result

    def link(self):
        for linker in self._get_linkers():
            linker(self)

    def _get_linkers(self):
        yield from self.linkers
        for child in self.children:
            yield from child._get_linkers()

    async def solve(self):
        with self.ctx.use():
            solved = set[UUID]()
            self.link()
            while deps := self.all(solved):
                deps.sort(key=lambda x: x.priority)

                deps = self._index(solved, deps)

                flatten_cache = {}
                for dependency in deps:
                    self.flatten_dependency(dependency, cache=flatten_cache)

                async with create_task_group() as tg:
                    for dependency in deps:
                        tg.start_soon(dependency.run)

                solved.update(x.id for x in deps)

    def _process_replace(self, deps: list[Dependency]):
        removed = set[UUID]()
        new = set[UUID]()
        for selector, dependency in self.replace:
            source = selector.resolve(self)
            self._by_id[source.id] = dependency
            if self._by_type.get(source.type, None) is source:
                assert dependency.type_constructor, (
                    "Replacing dependency should be type constructor"
                )
                self._by_type[source.type] = dependency
            self._index_one(dependency)
            removed.add(source.id)
            new.add(dependency.id)
        return [x for x in deps if x.id not in removed and x.id not in new] + list(
            self._by_id[x] for x in new
        ), removed

    def _index_one(self, dependency: Dependency):
        self._by_id.setdefault(dependency.id, dependency)
        if dependency.type_constructor:
            self._by_type.setdefault(dependency.type, dependency)

    def flatten_dependency(
        self,
        dependency: Dependency,
        visited: set[UUID] = set(),
        cache: dict | None = None,
    ) -> set[UUID]:
        if cache is None:
            cache = {}
        if dependency.id in cache:
            return cache[dependency.id]
        if dependency.id in visited:
            raise SolveError("Found self reference/loop in dependencies")

        visited = visited | {dependency.id}
        result = visited
        for dep in dependency._dependencies:
            result = result | self.flatten_dependency(dep, visited, cache)

        cache[dependency.id] = result
        return result

    def add(self, *dependencies: "Dependencies | Dependency | Dependable"):
        for dep in dependencies:
            if isinstance(dep, Dependencies):
                self.children.append(dep)
            else:
                self.bind(dep)
        return self

    def resolve[T](self, type: Type[T]) -> T:
        return self._by_type[type]._result

    def bind[T: Dependency | Dependable](self, dependency: T) -> T:
        self.dependencies.append(dependency.__dependency__())
        return dependency

    def rebuild(self, clone_all: bool = True, inplace: bool = False):
        clone = self.model_copy(deep=clone_all)
        if not inplace:
            self = clone
        self.dependencies = list(clone.all())
        self.linkers = list(clone._get_linkers())
        for dependency in clone.dependencies:
            dependency._dependencies = []
        self.children = []
        return self

    def add_linker(self, linker: Callable[["Self"], Any]):
        self.linkers.append(linker)
        return linker

    def visualize(self):
        solved = self.index()

        import graphviz

        graph = graphviz.Digraph()
        for dependency in solved:
            dependency = self._by_id[dependency]
            for sub in dependency._dependencies:
                graph.edge(sub.pretty(), dependency.pretty())
        print(graph.source)

    def index(self):
        with self.ctx.use():
            solved = set[UUID]()
            self.link()
            while deps := self.all(solved):
                deps.sort(key=lambda x: x.priority)
                deps = self._index(solved, deps)
                solved |= set(x.id for x in deps)
        return solved

    def _index(self, solved: set[UUID], deps: list[Dependency]):
        for dependency in deps:
            self._index_one(dependency)

        if self.replace:
            deps, ignore = self._process_replace(deps)
            solved.update(ignore)
            self.replace = []  # dont do same job twice if got new dependencies
        result: list[Dependency] = []
        for dependency in deps:
            try:
                dependency.link()
            except SkipDependency:
                solved.add(dependency.id)
                dependency.state = "skipped"
                continue
            result.append(dependency)
        return result

    def indexed(self):
        self.index()
        return self


class DependenciesModule(Dependencies, Module):
    @asynccontextmanager
    async def use_module(self):
        with self.ctx.use():
            yield
