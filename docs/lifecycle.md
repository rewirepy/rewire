# Lifecycle Management with Rewire

This example demonstrates how to use the `Rewire` library for managing the lifecycle of Python functions, both synchronous and asynchronous.

## Setting up your environment

First, let's import the required modules and create a `LifecycleModule` instance:

```python
from contextlib import asynccontextmanager
import anyio
from rewire import LifecycleModule

lm = LifecycleModule()  # create lifecycle manager
```

## Defining functions

Here are two examples of functions - an asynchronous function `my_async_function()`, and a synchronous function `my_sync_function()`.

```python
async def my_async_function():
    print("My async function ran")

def my_sync_function():
    print("My sync function ran")
```

## Starting functions

To start the functions, pass them to the `run` method of the lifecycle manager:

```python
lm.run(my_async_function())  # you can pass awaitables
lm.run(my_sync_function)  # you can also pass callables (will run in thread)
```

## Stopping functions

You can define stop callbacks that will be executed when the lifecycle manager is stopped:

```python
async def my_function_with_stop_callback():
    print("Running function with stop callback")

    async def stop():
        print("Stop callback called")

    async def stop_sync():
        print("Sync stop callback called")

    lm.on_stop(stop)  # you add stop hooks after start
    lm.on_stop(stop_sync)
```

## Using context managers

Define an asynchronous context manager to run before any `run()` functions and exit after all `stop()` functions:

```python
@asynccontextmanager
async def my_context_manager():
    print("Context manager entered")
    try:
        yield
    finally:
        print("Context manager exited")
```

Apply the context manager to the lifecycle manager:

```python
lm.contextmanager(my_context_manager())
```

## Running the lifecycle manager

Finally, use `anyio.run()` to start the lifecycle manager:

```python
anyio.run(lm.start, True)
```
