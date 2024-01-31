from contextlib import contextmanager
from contextvars import ContextVar
from typing import Type, overload
from uuid import uuid4
from pydantic import BaseModel, PrivateAttr

UNSET = object()


class Context[T](BaseModel):
    _ctx: ContextVar[T] | None = PrivateAttr(None)
    name: str | None = None

    @property
    def ctx(self):
        if self._ctx is not None:
            return self._ctx
        self._ctx = ContextVar(self.name or str(uuid4()))
        return self._ctx

    @contextmanager
    def use(self: "ContextVar[T] | Context[T]", value: T):
        if isinstance(self, Context):
            self = self.ctx

        token = self.set(value)
        try:
            yield value
        finally:
            self.reset(token)

    @overload
    def get[D](self, default: D) -> T | D:
        ...

    @overload
    def get(self) -> T:
        ...

    def get(self, default=UNSET):
        if default is UNSET:
            return self.ctx.get()
        return self.ctx.get(default)


def use_context_value[T](self: ContextVar[T] | Context[T], value: T):
    return Context.use(self, value)


class BoundCtx[T](Context[T]):
    _value: T = PrivateAttr()

    def use(self, value: T | None = None):
        return super().use(value or self._value)


class CTX(property):
    _context: Context | None = None

    @overload
    def __get__[T](self, __instance: None, __owner: Type[T]) -> Context[T]:
        ...

    @overload
    def __get__[T](self, __instance: T, __owner: Type[T]) -> BoundCtx[T]:
        ...

    def __get__[T](
        self, __instance: T | None, __owner: Type[T]
    ) -> Context[T] | BoundCtx[T]:
        if self._context is None:
            self._context = Context()
        if __instance is not None:
            ctx = BoundCtx()
            ctx._ctx = self._context.ctx
            ctx._value = __instance
            ctx.name = self._context.name
            return ctx
        return self._context
