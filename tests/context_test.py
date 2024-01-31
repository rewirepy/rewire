from pydantic import BaseModel

from rewire.context import CTX


class Test(BaseModel):
    ctx = CTX()


def test_object():
    with Test().ctx.use() as obj:
        assert obj.ctx.get() is obj
