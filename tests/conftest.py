import pytest

def pytest_addoption(parser: pytest.Parser):
    parser.addoption(
        "--docker-container",
        action="store",
        default=None,
        help="Commands will be execute in docker container",
    )
