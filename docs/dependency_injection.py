from typing import Annotated
from rewire import Dependency, Dependencies, TypeRef, InjectedDependency, InjectMarker
from anyio import run


async def my_dependency_function():
    print("Dependency ran")


first_dependency = Dependency(cb=my_dependency_function)


async def my_nested_dependency_function():
    print("Dependency with dependencies ran")


dependency_with_dependencies = Dependency(
    cb=my_nested_dependency_function,
    dependencies=[first_dependency],
)


async def my_int_factory() -> int:
    return 0


int_factory_dependency = Dependency(
    cb=my_int_factory,
    dependencies=[first_dependency],
    type=int,
)


async def my_int_consumer():
    """Consumes an integer value and prints it."""
    int_value = int_factory_dependency._result
    print(f"Received {int_value} from int factory")


int_consumer_dependency = Dependency(
    cb=my_int_consumer,
    dependencies=[TypeRef(type=int)],
    type=int,
)


@InjectedDependency.inject_into
async def str_factory() -> str:
    return "string from str factory"


@InjectedDependency.inject_into  # will inject only annotated attributes
async def str_wrapper(
    a: str_factory.Result,  # preferred way to inject from *specific* dependency (best type check)
    b: Annotated[str, str_factory],
    c: Annotated[str, TypeRef(type=str)],
    d: Annotated[str, InjectMarker()],  # will be injected
    e: str = "wrapped argument",  # will not be injected
) -> str:  # somehow update type to be used in next dependencies
    return f"{d!r} wrapped {e!r}"


@InjectedDependency.inject_all_into  # will inject all attributes
async def str_consumer2(
    a: str_factory.Result,
    b: Annotated[str, str_factory],
    c: Annotated[str, TypeRef(type=str)],
    d: Annotated[str, InjectMarker()],
    e: str = "default value",  # will be injected
):
    print(f"Got injected string: {e!r}")


dependencies = Dependencies()  # create container
dependencies.bind(first_dependency)  # add dependency to container
dependencies.bind(dependency_with_dependencies)
dependencies.add(
    Dependencies(
        dependencies=[
            int_factory_dependency,  # add dependencies to sub-container
            int_consumer_dependency,
            str_consumer2,
            str_wrapper,
            str_factory,
        ]
    )
)
run(dependencies.solve)
