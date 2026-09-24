"""Live-suite opt-in.

The `app` package imports through `[tool.pytest.ini_options] pythonpath = ["src"]` in
pyproject.toml. `tests.*` helpers (`tests.synthetic` and its siblings: test_client,
live_helpers, test_intake, test_template_shape, test_coverage) import through a
different mechanism entirely: pytest always imports every `conftest.py` it discovers,
and importing this root-level one -- no `__init__.py` sits beside it -- puts its own
directory, the repo root, on `sys.path`. `tests/` has no `__init__.py` of its own
either, so once the repo root is on `sys.path`, `tests.*` resolves as an implicit
namespace package (PEP 420), not through `pythonpath`, which only ever names `src`.
G14 (tests layout) moves this file; whatever it becomes must keep putting the repo
root on `sys.path`, or every `tests.*` import breaks. The `live` marker is declared in
pyproject.toml too and needs no wiring up here.
"""

import sys
from pathlib import Path

import pytest

# Keep repository-local test helpers importable after this conftest moves under tests/.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests marked 'live' (hits the real Kissflow dev tenant via KF_APP)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(
        reason="need --run-live to hit the real Kissflow dev tenant"
    )
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def _no_real_dotenv_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may read the developer's real `.env` (spec G2): `Settings`' own
    `load_dotenv()` call is a no-op here, for every test in this session.

    The settings tests that check `load_dotenv` itself patch it a second time, inside
    the test (as the clone's tests do), which overrides this default. The live suites
    still populate `os.environ` from `.env` -- through `tests/live_helpers.py`'s own
    parser, never through `load_dotenv()` -- so this fixture does not affect what
    values `load_settings()` sees there.
    """
    monkeypatch.setattr("app.infrastructure.config.settings.load_dotenv", lambda: None)
