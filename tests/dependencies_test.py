from contextlib import suppress
from typing import Annotated, Any
import pytest
from rewire.dependencies import (
    Dependencies,
    Dependency,
    InjectMarker,
    InjectedDependency,
    SolveError,
    TypeRef,
)


@pytest.mark.anyio
async def test_dependencies():
    async def foo():
        return 1

    async def get_result():
        return a._result

    a = Dependency(cb=foo)

    b = Dependency(dependencies=[a], cb=get_result)
    deps = Dependencies(dependencies=[a, b])

    await deps.solve()

    assert a._result == b._result == 1


@pytest.mark.anyio
async def test_duplicate():
    async def foo():
        return 1

    async def get_result():
        return a._result

    a = Dependency(cb=foo)

    b = Dependency(dependencies=[a], cb=get_result)
    deps = Dependencies(dependencies=[a, b, a, b])

    await deps.solve()

    assert a._result == b._result == 1


@pytest.mark.anyio
async def test_unrelated():
    async def foo():
        return 1

    async def get_result():
        return a._result

    a = Dependency(cb=foo)

    b = Dependency(dependencies=[a], cb=get_result)
    deps = Dependencies(dependencies=[b])

    with suppress(SolveError), pytest.raises(SolveError):
        await deps.solve()


@pytest.mark.anyio
async def test_optional():
    async def foo():
        return 1

    async def get_result():
        return a._result

    a = Dependency(cb=foo)

    b = Dependency(dependencies=[a], cb=get_result, optional=True)
    deps = Dependencies(dependencies=[b])

    await deps.solve()
    assert b.state == "skipped"


@pytest.mark.anyio
async def test_circular():
    async def foo():
        return 1

    async def get_result():
        return a._result

    a = Dependency(cb=foo)

    b = Dependency(dependencies=[a], cb=get_result)
    a.dependencies.append(b)
    deps = Dependencies(dependencies=[a, b])

    with suppress(SolveError), pytest.raises(SolveError):
        await deps.solve()


@pytest.mark.anyio
async def test_typed():
    @InjectedDependency.inject_into
    async def foo() -> int:
        return 1

    @InjectedDependency.inject_into
    async def get_result(
        a: Annotated[Any, foo],
        b: Annotated[Any, foo],
        c: Annotated[Any, TypeRef(type=int)],
        d: Annotated[int, InjectMarker()],
        e: foo.Result,
        u: int = 0,  # will not be injected
    ):
        assert a is b is c is d is e is not u
        return a

    @InjectedDependency.inject_all_into
    async def get_result_inject_all(
        a: Annotated[Any, foo],
        b: Annotated[Any, foo],
        c: Annotated[Any, TypeRef(type=int)],
        d: Annotated[int, InjectMarker()],
        e: foo.Result,
        u: int,  # will be injected
    ):
        assert a is b is c is d is e is u
        return a

    deps = Dependencies(dependencies=[foo, get_result, get_result_inject_all])

    await deps.solve()


@pytest.mark.anyio
async def test_typed_bad_order():
    @InjectedDependency.inject_into
    async def foo():
        return 1

    @InjectedDependency.inject_into
    async def get_result(a: foo.Result):
        return a

    deps = Dependencies(dependencies=[foo, get_result])

    await deps.solve()


@pytest.mark.anyio
async def test_type_wrapper():
    @InjectedDependency.inject_into
    async def foo() -> int:
        return 1

    @InjectedDependency.inject_all_into
    async def wrap_result(a: int) -> int:
        return a + 1

    wrap_result.priority = -1

    @InjectedDependency.inject_all_into
    async def get_result(a: int):
        assert a == 2
        return a

    deps = Dependencies(dependencies=[get_result, wrap_result, foo])

    await deps.solve()


@pytest.mark.anyio
async def test_runtime_add():
    did_run = False

    @InjectedDependency.inject_into
    async def foo():
        nonlocal did_run

        @InjectedDependency.inject_into
        async def get_result(a: foo.Result):
            nonlocal did_run
            did_run = True
            return a

        deps.dependencies.append(get_result)
        return 1

    deps = Dependencies(dependencies=[foo])

    await deps.solve()

    assert did_run


@pytest.mark.anyio
async def test_replace_by_id():
    @InjectedDependency.inject_into
    async def foo():
        return 1

    @InjectedDependency.inject_into
    async def foo_replace():
        return 2

    @InjectedDependency.inject_into
    async def get_result(a: foo.Result):
        return a

    deps = Dependencies(dependencies=[foo, get_result], replace=[(foo, foo_replace)])

    await deps.solve()
    assert get_result._result == foo_replace._result
    assert foo.state == "pending"


@pytest.mark.anyio
async def test_replace_by_type():
    @InjectedDependency.inject_into
    async def foo() -> int:
        return 1

    @InjectedDependency.inject_into
    async def foo_replace():
        return 2

    @InjectedDependency.inject_all_into
    async def get_result(a: int) -> int:
        return a

    deps = Dependencies(
        dependencies=[foo, get_result], replace=[(TypeRef(type=int), foo_replace)]
    )

    await deps.solve()
    assert get_result._result == foo_replace._result
    assert foo.state == "pending"


@pytest.mark.anyio
async def test_rebuild():
    @InjectedDependency.inject_into
    async def foo():
        return 1

    @InjectedDependency.inject_into
    async def get_result(a: foo.Result):
        return a

    deps = Dependencies(dependencies=[foo, get_result])
    deps = deps.rebuild(True)
    await deps.solve()
    assert (
        foo.state == "pending"
        and get_result.state == "pending"
        and deps.dependencies[0].state == "done"
        and deps.dependencies[1].state == "done"
    )


@pytest.mark.anyio
async def test_linked():
    did_run = False

    @InjectedDependency.inject_into
    async def foo():
        return 1

    @InjectedDependency.inject_into
    async def get_result(a: foo.Result):
        nonlocal did_run
        did_run = True
        return a

    linked_deps = Dependencies(dependencies=[get_result])
    deps = Dependencies(dependencies=[foo])
    deps.add_linker(lambda deps: deps.add(linked_deps.rebuild()))

    await deps.solve()

    assert did_run


@pytest.mark.anyio
async def test_bind():
    async def foo():
        return 1

    a = Dependency(cb=foo)

    deps = Dependencies()
    deps.bind(a)

    await deps.solve()
