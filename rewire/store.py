from contextlib import asynccontextmanager
from typing import Any
from rewire.context import CTX
from rewire.space import Module


class SimpleStore[T]:
    value: T

    def set(self, value: T):
        self.value = value

    def get(self):
        return self.value


class StoreModule(Module):
    """Store anything in space context with this one simple trick"""

    ctx = CTX()

    data: dict[str, Any] = {}

    @classmethod
    def get(cls):
        return cls.ctx.get()

    @asynccontextmanager
    async def use_module(self):
        with self.ctx.use():
            yield
