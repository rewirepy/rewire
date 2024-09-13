import ast
from contextvars import ContextVar
from functools import lru_cache
import json
from os import getenv
import os
from pathlib import Path
from textwrap import dedent
from typing import (
    Annotated,
    Any,
    Callable,
    ClassVar,
    Dict,
    Literal,
    Optional,
    Self,
    Type,
    cast,
    overload,
)
from loguru import logger
from pydantic import BaseModel, Field, TypeAdapter
import yaml
from rewire.classproperty import classproperty
from rewire.context import use_context_value
import inspect
from rewire.dependencies import Dependency, TypeRef
from rewire.space import Module

from rewire.store import SimpleStore

CONFIG_FILE = getenv("CONFIG_FILE", "./config.yaml")

UNSET = object()


cwdContext = ContextVar("rewire.config.cwdConfig", default="./")
fileContext = ContextVar("rewire.config.fileContext", default=CONFIG_FILE)
rootContext = ContextVar("rewire.config.rootContext")


class ConfigLoader(yaml.SafeLoader):
    pass


class EnvRequired(Exception):
    pass


class PyCode(BaseModel):
    code: str
    cwd: str = Field(default_factory=cwdContext.get)
    file: str = Field(default_factory=fileContext.get)

    def execute(self):
        return eval(
            self.code,
            {"this": rootContext.get(), "self": rootContext.get()},
            self.functions(),
        )

    def functions(self):
        return {"include": self.include, "getenv": getenv}

    def include(self, file: str):
        with (
            use_context_value(cwdContext, self.cwd),
            use_context_value(fileContext, self.file),
        ):
            return load_yaml(file)


class PyExecCode(PyCode):
    def execute(self):
        def function(self, this) -> Any:
            raise RuntimeError("This function should be patched")

        function_code = ast.parse(dedent(inspect.getsource(function)))
        assert isinstance(function_code.body[0], ast.FunctionDef)

        function_code.body[0].body = ast.parse(self.code).body
        filename = f"<!pyexec {hex(id(self))}>"
        compiled_function = compile(function_code, filename, "exec")
        for const in compiled_function.co_consts:
            if not isinstance(const, type(compiled_function)):
                continue
            if const.co_filename == filename and const.co_name == function.__name__:
                function.__code__ = const
                break

        return function(rootContext.get(), rootContext.get())


class EvalDict(dict):
    __pydantic_validator__ = None

    def __getitem__(self, __k):
        if __k not in self:
            raise AttributeError(__k)
        value = super().__getitem__(__k)

        if isinstance(value, PyCode):
            return value.execute()

        if isinstance(value, dict):
            return type(self)(value)

        return value

    def __getattribute__(self, __name: str) -> Any:
        try:
            return super().__getattribute__(__name)
        except AttributeError:
            return self.__getitem__(__name)  # type: ignore


def load_yaml_env(loader, node: yaml.ScalarNode):
    value = getenv(*node.value.split(":", 1))
    if value is None:
        raise EnvRequired(f'env variable {node.value.split(":", 1)[0]!r} required')
    return value


def load_yaml_include(loader, node: yaml.ScalarNode):
    return load_yaml(node.value)


def load_yaml_py(load, node: yaml.ScalarNode):
    return PyCode(code=node.value)


def load_yaml_pyexec(load, node: yaml.ScalarNode):
    return PyExecCode(code=node.value)


def load_yaml_yaml(load, node: yaml.ScalarNode):
    return prepare_yaml(yaml.load(node.value, ConfigLoader))


ConfigLoader.add_constructor("!env", load_yaml_env)
ConfigLoader.add_constructor("!include", load_yaml_include)
ConfigLoader.add_constructor("!py", load_yaml_py)
ConfigLoader.add_constructor("!pyexec", load_yaml_pyexec)
ConfigLoader.add_constructor("!yaml", load_yaml_yaml)


@overload
def merge[K, T, KO, TO](
    source: dict[K, T], overlay: dict[KO, TO]
) -> dict[K | KO, T | TO]: ...


@overload
def merge[T](source: Any, overlay: T) -> T: ...


def merge(source: dict | list | Any, overlay: dict | list | Any):
    if isinstance(source, dict | list):
        source = source.copy()
    if isinstance(source, dict) and isinstance(overlay, dict):
        for key, value in overlay.items():
            source[key] = merge(source.get(key, None), value)
        return source
    return overlay


def render_py(value, root=UNSET):
    if root is UNSET:
        root = value
    if isinstance(value, dict):
        new_value = {k: render_py(v, root=root) for k, v in value.items()}
        value.update(new_value)
        return EvalDict(value)
    if isinstance(value, list):
        new_value = [render_py(v, root=root) for v in value]
        value.clear()
        value.extend(new_value)
        return value
    if isinstance(value, PyCode):
        return render_py(value.execute(), root=root)
    return value


def load_yaml(file_: str | Path):
    cwd = cwdContext.get().removesuffix("/") + "/"
    file_ = os.path.join(cwd, file_)
    with (
        open(file_, encoding="utf-8") as f,
        use_context_value(fileContext, file_),
        use_context_value(cwdContext, os.path.dirname(file_)),
    ):
        value = yaml.load(f, ConfigLoader)
        return prepare_yaml(value)


def prepare_yaml(value):
    with use_context_value(rootContext, None):
        return EvalDict({"d": value}).d


def set_by_key(key, value, data):
    if key:
        for k in key.split(".")[:-1]:
            data = data.setdefault(k, {})
        data[key.split(".")[-1]] = value
    else:
        data.update(value)


def get_by_key(key, data):
    if key is None:
        return data
    if "." in key:
        key, next_key = key.split(".", 1)
        return get_by_key(next_key, data.get(key, {}))
    return data.get(key, {})


def merge_env(data: Dict):  # /NOSONAR
    remap_config = getenv("CONFIG_REWIRE_ENV_REMAP", {})
    if isinstance(remap_config, str):
        remap_config = json.loads(remap_config)
        assert isinstance(remap_config, dict)

    for key, value in os.environ.items():
        remapped = key in remap_config
        if remapped:
            key = remap_config[key]

        if not key.startswith("CONFIG_") and not remapped:
            continue

        if not remapped:
            key = key.removeprefix("CONFIG_")
            key = key.replace("_", ".").replace("..", "_")

        if key.endswith("_.JSON") or remapped and key.endswith(":json"):
            key = key.removesuffix("_.JSON").removesuffix(":json")
            value = json.loads(value)
        elif key.endswith("_.YAML") or remapped and key.endswith(":yaml"):
            key = key.removesuffix("_.YAML").removesuffix(":yaml")
            value = yaml.load(value, ConfigLoader)
            value = prepare_yaml(value)

        set_by_key(key, value, data)
    return data


@lru_cache()
def parse_file(file: str | Path, silent: bool = False):
    try:
        raw_config = TypeAdapter(Dict[str, Any]).validate_python(load_yaml(file) or {})
    except FileNotFoundError as e:
        if not silent:
            logger.error(e)
        raw_config = {}

    raw_config = merge_env(raw_config)

    with use_context_value(rootContext, raw_config):
        raw_config = EvalDict({"d": raw_config}).d

    with use_context_value(rootContext, raw_config):
        return render_py(raw_config)


def extract_config_by_path(path: str, model: BaseModel):
    config = model

    for part in path.split("."):
        config = getattr(config, part, {})

    return config


def gen_config_model[TBM: BaseModel](path: str, model: Type[TBM], name: str = "Config"):
    Model = model  # /NOSONAR

    field, _, next_ = path.partition(".")
    if next_:
        Model = gen_config_model(next_, model, f"{field.capitalize()}{name}")

    store: SimpleStore[TBM] = SimpleStore()
    no_required_args = True

    for param in inspect.signature(Model).parameters.values():  # type: ignore
        if param.default is inspect._empty:
            no_required_args = False

    exec(
        f"field = Field(default_factory=Model) if noRequiredArgs else Field(...)\n"
        f"class {name}(BaseModel):\n"
        f"    {field}: Model = field\n"
        f"store.set({name})\n",
        {
            "store": store,
            "Model": Model,
            "BaseModel": BaseModel,
            "Field": Field,
            "noRequiredArgs": no_required_args,
        },
    )

    value = store.get()
    if not value:
        raise RuntimeError("evaluation failed")

    return value


class ConfigModule(Module):
    config: dict = {}
    config_file: str = CONFIG_FILE

    def init(self):
        self.config = cast(dict, parse_file(self.config_file))  # type: ignore

    def patch(self, override: dict):
        self.config = merge(self.config, override)


class EnvironmentModule(Module):
    env: Literal["production", "dev"] = "production"

    def init(self):
        config = ConfigModule.get(None)
        if (
            config is not None
            and config.config.get("rewire", {}).get("env", getenv("ENV", None)) == "dev"
        ):
            self.env = "dev"

    @classmethod
    def current_env(cls):
        self = EnvironmentModule.get(None)
        return "dev" if self is None else self.env


@overload
def config[TBM: BaseModel](
    model: Type[TBM], *, path: Optional[str] = ".", fallback: Any = None
) -> TBM: ...


@overload
def config[TBM: BaseModel](
    *, path: Optional[str] = ".", fallback: Any = None
) -> Callable[[Type[TBM]], TBM]: ...


def config(model: Any = UNSET, *, path: Optional[str] = ".", fallback: Any = None):
    """fills base model from file fields"""

    def wrapper[TBM: BaseModel](config: Type[TBM]) -> TBM:
        config_path = update_path(config.__module__, path or ".")

        data = gen_config_model(config_path, config)
        try:
            raw_config = ConfigModule.get().config

            return cast(
                config,
                extract_config_by_path(config_path, data.model_validate(raw_config)),
            )
        except LookupError:
            if fallback is None:
                raise
            return config.model_validate(fallback)

    if model is not UNSET:
        return wrapper(model)

    return wrapper


def update_path(config_path: str, post_path: str):
    level = 0

    while post_path.startswith("."):
        level -= 1
        post_path = post_path[1:]

    if level == 0:
        return post_path

    for _ in range(1, -level):
        config_path = ".".join(config_path.split(".")[:-1])

    if post_path:
        config_path = f"{config_path}.{post_path}".strip(".")
    return config_path


class ConfigDependency(BaseModel):
    _dependency: ClassVar[Dependency[Self] | None] = None
    __location__: ClassVar[str] = "."
    __fallback__: ClassVar[dict | None] = None

    @classproperty
    @classmethod
    def dependency(cls) -> Dependency[Self]:
        if cls._dependency is None:

            async def resolve():
                return config(cls, path=cls.__location__, fallback=cls.__fallback__)

            cls._dependency = Dependency[Self](
                cb=resolve, type=cls, label=f"Config ({cls.__module__}.{cls.__name__})"
            )
        return cls._dependency

    @classproperty
    @classmethod
    def Value(cls) -> Type[Self]:
        return Annotated[cls, TypeRef(type=cls)]  # type: ignore

    @classmethod
    def __dependency__(cls):
        return cls.dependency
