import asyncio
import inspect


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "asyncio: mark test as async and execute it on an event loop",
    )


def pytest_pyfunc_call(pyfuncitem):
    test_fn = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_fn):
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(test_fn(**kwargs))
    return True
