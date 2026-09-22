"""Live-suite opt-in. Import paths come from `[tool.pytest.ini_options] pythonpath` in
pyproject.toml (`src` for the `app` package, `.` for `tests.*` helpers), and the `live`
marker is declared there too — neither needs wiring up by hand any more.
"""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests marked 'live' (hits the real Kissflow dev tenant via KF_APP)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="need --run-live to hit the real Kissflow dev tenant")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
