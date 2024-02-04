# Lifecycle

## Starting your functions
from contextlib import asynccontextmanager
import anyio
from rewire import LifecycleModule

lm = LifecycleModule()  # create lifecycle manager


async def my_async_function():
    print("My async function ran")


def my_sync_function():
    print("My sync function ran")


lm.run(my_async_function())  # you can pass awaitables
lm.run(my_sync_function)  # you can also pass callables (will run in thread)

## Stopping your functions
# stop task will not run until all .run functions are done


async def my_function_with_stop_callback():
    print("Running function with stop callback")

    async def stop():
        print("Stop callback called")

    async def stop_sync():
        print("Sync stop callback called")

    lm.on_stop(stop)  # you add stop hooks after start
    lm.on_stop(stop_sync)


lm.run(my_function_with_stop_callback())


## Using context managers

# Context managers will enter before any .run function and exit after all .stop functions


@asynccontextmanager
async def my_context_manager():
    print("Context manager entered")
    try:
        yield
    finally:
        print("Context manager exited")


lm.contextmanager(my_context_manager())

## Running it
anyio.run(lm.start, True)
