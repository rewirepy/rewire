from pydantic import BaseModel
from rewire.config import ConfigModule, PyExecCode, config, rootContext
from rewire.context import use_context_value
from rewire.space import Space


def test_config():
    space = Space().add(ConfigModule(config={"config_test": {"value": 123}}))
    with space.ctx.use():

        @config()
        class Test(BaseModel):
            value: int

        assert Test.value == 123


def test_pyexec():
    value = {}
    with use_context_value(rootContext, value):
        code = PyExecCode(code="if self is this:\n return self")
        assert value is code.execute()
