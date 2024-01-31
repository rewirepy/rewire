from typing import Callable


class classproperty[T](property):
    def __init__(self, cb: Callable[..., T]) -> None:
        self.cb = cb
        super().__init__()

    def __get__(self, _, owner) -> T:
        return self.cb.__func__(owner)  # type: ignore
