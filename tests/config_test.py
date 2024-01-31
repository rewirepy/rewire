from pydantic import BaseModel
from rewire.config import ConfigModule, config
from rewire.space import Space


def test_config():
    space = Space().add(ConfigModule(config={"config_test": {"value": 123}}))
    with space.ctx.use():

        @config()
        class Test(BaseModel):
            value: int

        assert Test.value == 123
