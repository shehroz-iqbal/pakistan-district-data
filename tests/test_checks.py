"""Every data-quality check from pipeline/checks.py becomes one test case."""

import duckdb
import pytest

from pipeline import checks
from pipeline.common import DB_PATH

GROUPS = [
    checks.district_structure,
    checks.province_reconciliation,
    checks.national_headlines,
    checks.identities,
    checks.cross_table,
    checks.ranges_and_completeness,
    checks.geometry,
]


def _collect():
    if not DB_PATH.exists():
        return []
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return [c for group in GROUPS for c in group(con)]
    finally:
        con.close()


ALL = _collect()


@pytest.mark.skipif(not ALL, reason="Database not built yet: run `python -m pipeline.run` first.")
@pytest.mark.parametrize("check", ALL, ids=[f"{c.group}: {c.name}" for c in ALL])
def test_check(check):
    assert check.passed, check.detail
