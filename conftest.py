from pathlib import Path
import asyncio
import inspect
import sys


def _ensure_repo_test_paths() -> None:
    """Make repo-root pytest runs resolve packages that live under ark-core."""

    repo_root = Path(__file__).resolve().parent
    ark_core_root = repo_root / "ark-core"
    ark_core_root_str = str(ark_core_root)
    if ark_core_root_str not in sys.path:
        sys.path.insert(0, ark_core_root_str)


_ensure_repo_test_paths()


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
