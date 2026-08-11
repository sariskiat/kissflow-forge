import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live", action="store_true", default=False,
        help="run tests marked 'live' (hits the real Kissflow dev tenant via KF_APP)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: hits the real Kissflow dev tenant (KF_APP) — skipped unless --run-live"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="need --run-live to hit the real Kissflow dev tenant")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
