from datetime import time, timedelta
import logging
from os import PathLike
import sys
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    TextIO,
    Type,
    Union,
    runtime_checkable,
)
import warnings

import loguru
import builtins
from pydantic import BaseModel
from rewire.config import config
from rewire.lifecycle import LifecycleModule
from rewire.space import Module

if TYPE_CHECKING:
    from loguru import (
        Message,
        FormatFunction,
        FilterFunction,
        FilterDict,
        RotationFunction,
        RetentionFunction,
        CompressionFunction,
    )
else:
    FormatFunction = Any
    FilterFunction = Any
    FilterDict = Any
    RotationFunction = Any
    RetentionFunction = Any
    CompressionFunction = Any
    Message = Any

logger = loguru.logger

print_ = builtins.print
showwarning_ = warnings.showwarning


@runtime_checkable
class Writable(Protocol):
    def write(self, message: "Message") -> None:
        ...


class BaseSink(BaseModel, arbitrary_types_allowed=True):
    level: Optional[Union[str, int]] = None
    format: Optional[Union[str, "FormatFunction"]] = None
    filter: Optional[Union[str, "FilterFunction", "FilterDict"]] = None
    colorize: Optional[bool] = None
    serialize: Optional[bool] = None
    backtrace: Optional[bool] = None
    diagnose: Optional[bool] = None
    enqueue: Optional[bool] = True
    catch: Optional[bool] = None
    kwargs: Dict[str, Any] = {}


class PythonSink(BaseSink):
    sink: Union[
        TextIO,
        Writable,
        Callable[["Message"], None],
        logging.Handler,
        Callable[["Message"], Awaitable[None]],
    ]


class FileSink(BaseSink):
    sink: Union[str, PathLike[str]]

    rotation: Optional[Union[str, int, time, timedelta, "RotationFunction"]] = None
    retention: Optional[Union[str, int, timedelta, "RetentionFunction"]] = None
    compression: Optional[Union[str, "CompressionFunction"]] = None
    delay: Optional[bool] = None
    mode: Optional[str] = None
    buffering: Optional[int] = None
    encoding: Optional[str] = None


class RuntimeSink(BaseSink):
    @property
    def sink(self):
        return self.get_sink()

    def get_sink(self):
        raise NotImplementedError()


class StdoutSink(RuntimeSink):
    def get_sink(self):
        return sys.stdout


def log_print(
    *values: object,
    sep: str = " ",
    end: Optional[str] = None,
    **kw,
):
    if kw:
        return print_(*values, sep=sep, end=end if isinstance(end, str) else "\n", **kw)
    warnings.warn("print is deprecated, use logger.debug instead", stacklevel=2)
    data = f"{sep.join(map(str, values))}{end if isinstance(end, str) else ''}"
    logger.opt(depth=1).debug(data)


def showwarning(
    message: Warning | str,
    category: Type[Warning],
    filename: str,
    lineno: int,
    line: str | None = ...,
    *_,
    **__,
):
    msg = warnings.formatwarning(
        message,
        category,
        filename,
        lineno,
        line,
    ).removesuffix("\n")
    logger.opt(depth=2).warning(msg)


class LoggerConfig(BaseModel):
    sinks: List[PythonSink | FileSink | StdoutSink | RuntimeSink] = [
        StdoutSink(level="info")
    ]
    patch_builtins: bool = True
    register_stop: bool = True


class LoggerModule(Module):
    _config: LoggerConfig | None = None

    @property
    def config(self):
        if self._config is None:
            self._config = config(LoggerConfig)
        return self._config

    def init(self):
        self.setup()

    def setup(self):
        if self.config.sinks:
            logger.remove()
        for sink in self.config.sinks:
            logger.add(
                sink.sink,  # type: ignore
                **sink.model_dump(exclude={"kwargs", "sink"}, exclude_none=True),
                **sink.kwargs,
            )

        if self.config.patch_builtins:
            builtins.print = log_print
            warnings.showwarning = showwarning

        if self.config.register_stop:
            LifecycleModule.get().on_stop(self.stop)
            self.config.register_stop = False

        return self

    def sink(
        self,
        *sink: PythonSink | FileSink | StdoutSink | RuntimeSink,
        setup: bool = True,
    ):
        self.config.sinks.extend(sink)
        if setup:
            self.setup()
        return self

    async def stop(self):
        await logger.complete()
