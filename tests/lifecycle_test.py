from contextlib import asynccontextmanager
import pytest

from rewire.lifecycle import LifecycleModule


@pytest.mark.anyio
async def test_simple():
    lm = LifecycleModule()
    did_run = False

    async def test_run():
        nonlocal did_run
        did_run = True

    did_stop = False

    async def test_stop():
        nonlocal did_stop
        did_stop = True

    lm.on_stop(test_stop)
    lm.run(test_run())

    await lm.start(run_stop=False)
    assert not did_stop and did_run
    await lm.stop()

    assert did_run and did_stop


@pytest.mark.anyio
async def test_context():
    lm = LifecycleModule()
    did_run = False
    did_stop = False

    @asynccontextmanager
    async def test_context():
        nonlocal did_run, did_stop
        did_run = True
        yield
        did_stop = True

    async def test_context_ran():
        assert not did_stop and did_run

    lm.run(test_context_ran())
    lm.contextmanager(test_context())

    await lm.start()
    assert did_run and did_stop
