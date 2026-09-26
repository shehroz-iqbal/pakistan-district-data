import duckdb
import pytest

from pipeline.common import DB_PATH


@pytest.fixture(scope="session")
def con():
    if not DB_PATH.exists():
        pytest.skip("Database not built yet: run `python -m pipeline.run` first.")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()
