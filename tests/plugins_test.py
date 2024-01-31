import pytest
from rewire.dependencies import Dependencies, DependenciesModule
from rewire.lifecycle import LifecycleModule

from rewire.plugins import simple_plugin, StagesModule
from rewire.space import Space


@pytest.mark.anyio
async def test_setup():
    async with Space(only=[StagesModule, DependenciesModule]).init().use():
        plugin = simple_plugin(load=False)
        did_run = False

        @plugin.setup()
        def test():
            nonlocal did_run
            did_run = True

        await plugin.solve()
        assert did_run


@pytest.mark.anyio
async def test_config():
    async with Space(only=[StagesModule, DependenciesModule]).init().use():
        plugin = simple_plugin(load=False)
        config = plugin.config()
        assert config.requirements[0] == "test"


@pytest.mark.anyio
async def test_stages():
    async with Space(only=[StagesModule, DependenciesModule]).init().use():
        plugin1 = simple_plugin(load=False)
        plugin2 = simple_plugin(load=False)
        plugin_unused = simple_plugin(load=False, bind=False)
        did_run = 0

        @plugin2.setup(priority=-1, stage=2)
        async def test2():
            nonlocal did_run
            did_run += 1
            return did_run

        @plugin1.setup(priority=-2, stage=1)
        async def test1():
            nonlocal did_run
            did_run += 1
            return did_run

        @plugin_unused.setup(priority=-2, stage=2)
        async def test3():
            nonlocal did_run
            did_run += 1
            return did_run

        await Dependencies.ctx.get().solve()
        assert test1._result == 1 and test2._result == 2


@pytest.mark.anyio
async def test_run():
    async with Space(
        only=[StagesModule, DependenciesModule, LifecycleModule]
    ).init().use():
        plugin = simple_plugin(load=False)
        did_run = 0

        @plugin.setup()
        async def test() -> int:
            return 1

        @plugin.run()
        async def test1(item: int):
            nonlocal did_run
            did_run += item

        await DependenciesModule.get().solve()
        await LifecycleModule.get().start()
        assert did_run
