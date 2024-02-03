# Dependency Injection in Python using Rewire library

## Overview

Dependency injection is a design pattern that allows decoupling the components of an application by injecting their dependencies instead of hard-coding them. In this document, we will explore how to use
the Rewire library to implement dependency injection in Python.

## Dependencies

### Simple Dependency

```python
from rewire import Dependency

async def my_dependency_function():
    print("Dependency ran")

first_dependency = Dependency(cb=my_dependency_function)
```

In the example above, we define a simple dependency called `first_dependency`, which is an instance of the `Dependency` class. It has a callback function `my_dependency_function` that gets executed when

### Dependency with Dependencies

```python
async def my_nested_dependency_function():
    print("Dependency with dependencies ran")

dependency_with_dependencies = Dependency(
    cb=my_nested_dependency_function, 
    dependencies=[first_dependency],
)
```

In this example, we define a dependency `dependency_with_dependencies`, which depends on the previously defined `first_dependency`. `dependency_with_dependencies` will run only after first_dependency is ran

### Dependency that Produces a Type

```python
async def my_int_factory() -> int:
    return 0

int_factory_dependency = Dependency(
    cb=my_int_factory,
    dependencies=[first_dependency],
    type=int,
)
```

In this example, we define a dependency `int_factory_dependency`, which is responsible for producing an integer value. It has a callback function `my_int_factory` that returns the required integer value and depends on the previously defined `first_dependency`.

### Dependency that consumes a Type

```python
from rewire import TypeRef

async def my_int_consumer():
    """Consumes an integer value and prints it."""
    int_value = int_factory_dependency._result
    print(f"Received {int_value} from int factory")

int_consumer_dependency = Dependency(
    cb=my_int_consumer,
    dependencies=[TypeRef(type=int)],
    type=int,
)
```

In this example, we define a dependency `int_consumer_dependency`, which requires an integer value. It has a callback function `my_int_consumer` that consumes the integer value and prints it. The required integer value is provided as a dependency of this dependency.

## Automatically Injecting Dependencies using Annotations

```python
from typing import Annotated
from rewire import InjectedDependency, TypeRef

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

```

In this example, we demonstrate how to automatically inject dependencies using annotations. We define three functions (`str_wrapper`, `str_consumer`, and `str_consumer2`) that have dependencies injected
using Rewire's `@InjectedDependency` decorator. The `str_factory` dependency is defined as a simple factory function and can be automatically injected into any other dependency function with `Annotated`.

## Solving Dependencies

### Constructing Dependencies

To solve dependencies, we first need to construct them and define their relationships. We do this by creating a `Dependencies` container using the `rewire.Dependencies()` constructor:

```python
from rewire import Dependencies

dependencies = Dependencies()  # create container
```

Next, we add dependencies to the container using the `bind()` method:

```python
dependencies.bind(first_dependency)  # add dependency to container
dependencies.bind(dependency_with_dependencies)
```

We can also define and bind nested dependencies by creating a new `Dependencies` instance with the required dependencies:

```python
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
```

### Running it

Finally, we can solve and execute all dependencies by calling the `solve()` method on our main container:

```python
from anyio import run
run(dependencies.solve)
```

This will recursively find all dependencies, resolve them based on their defined relationships, and call their respective functions. This asynchronous approach ensures proper order of execution and decoupling of components from each other.
