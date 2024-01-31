from contextlib import asynccontextmanager
from typing import AsyncContextManager, ClassVar, Self, Sequence, Type, overload
from typing_extensions import Unpack
from pydantic import BaseModel
from pydantic.config import ConfigDict

from rewire.context import CTX

UNSET = object()


class ModuleParams(ConfigDict, total=False):
    register: bool


class Module(BaseModel):
    def __init_subclass__(cls, **kwargs: Unpack[ModuleParams]):
        if kwargs.pop("register", True):
            Space._modules.append(cls)
        return super().__init_subclass__(**kwargs)

    def init(self):
        ...

    @overload
    @classmethod
    def get[V](cls, default: V) -> Self | V:
        ...

    @overload
    @classmethod
    def get(cls) -> Self:
        ...

    @classmethod
    def get(cls, default=UNSET):
        return Space.get(cls, default)

    @asynccontextmanager
    async def use_module(self):
        yield


class MultiAsyncContextManager:
    def __init__(self, managers: Sequence[AsyncContextManager]) -> None:
        self.managers = managers

    async def __aenter__(self, *args):
        for manager in self.managers:
            await manager.__aenter__(*args)

    async def __aexit__(self, *args):
        exceptions = []

        for manager in self.managers[::-1]:
            try:
                await manager.__aexit__(*args)
            except Exception as e:
                exceptions.append(e)
        if len(exceptions) > 1:
            raise ExceptionGroup("Multiple exceptions in context managers", exceptions)
        if len(exceptions) == 1:
            raise exceptions[0]


class Space(BaseModel):
    _modules: ClassVar[list[Type[Module]]] = []
    ctx = CTX()
    modules: dict[Type, Module] = {}
    only: list[Type[Module]] | None = None

    def init(self):
        with self.ctx.use():
            modules = self.only
            if modules is None:
                modules = self._modules
            for module in modules:
                if module in self.modules:
                    continue
                self.modules[module] = module()
                self.modules[module].init()
            return self

    @overload
    @classmethod
    def get[T, V](cls, module: Type[T], default: V) -> T | V:
        ...

    @overload
    @classmethod
    def get[T](cls, module: Type[T]) -> T:
        ...

    @classmethod
    def get[T, V](cls, module: Type[T], default: V = UNSET) -> T | V:
        if default is not UNSET:
            self = cls.ctx.get(UNSET)
            if self is UNSET:
                return default  # type: ignore
            return self.modules.get(module, default)  # type: ignore
        self = cls.ctx.get()
        return self.modules[module]  # type: ignore

    def add(self, *modules: Module):
        for module in modules:
            self.modules[type(module)] = module
        return self

    @asynccontextmanager
    async def use(self):
        with self.ctx.use():
            async with MultiAsyncContextManager(
                [x.use_module() for x in self.modules.values()]
            ):
                yield
