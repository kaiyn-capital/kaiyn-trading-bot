import os

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-db",
        action="store_true",
        default=False,
        help="run opt-in PostgreSQL integration tests",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-db") and os.environ.get("TEST_DATABASE_URL"):
        return

    skip_db = pytest.mark.skip(reason="requires --run-db and TEST_DATABASE_URL for PostgreSQL integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_db)
