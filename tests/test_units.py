"""Unit tests for the small functions everything else relies on."""

import pandas as pd
import pytest
from shapely.geometry import box

from pipeline.census import apply_fixes
from pipeline.common import district_id, match_key, slugify, title_name
from pipeline.geometry import assign


def test_slugify_and_ids():
    assert slugify("Dera Ghazi Khan") == "dera_ghazi_khan"
    assert slugify("  GULSHAN-E-IQBAL ") == "gulshan_e_iqbal"
    assert district_id("PB", "DERA GHAZI KHAN") == "pb_dera_ghazi_khan"


def test_title_name():
    assert title_name("TANDO MUHAMMAD KHAN") == "Tando Muhammad Khan"


@pytest.mark.parametrize("raw, key", [
    ("D.I.KHAN", "D I KHAN"),
    ("Aranji Sub", "ARANJI"),
    ("BABA_KOT", "BABA KOT"),
    ("GULSHAN E IQBAL TOWN", "GULSHAN E IQBAL"),
    ("CLIFTON CANTONMENT", "CLIFTON"),
])
def test_match_key(raw, key):
    assert match_key(raw) == key


def _table():
    return pd.DataFrame({
        "province_code": ["SD", "SD", "PB"],
        "name_admin_unit": ["TANDO AHYAR", "TANDO AHYAR", "TANDO AHYAR"],
        "all_sexes": [1, 2, 3],
    })


def test_fix_applies_to_matching_province_only():
    tables = {"t01": _table()}
    fix = {"id": "X", "table": "t01", "province": "sindh", "match": {"name_admin_unit": "TANDO AHYAR"},
           "set": {"name_admin_unit": "TANDO ALLAHYAR"}, "expected_rows": 2}
    apply_fixes(tables, [fix])
    assert list(tables["t01"]["name_admin_unit"]) == ["TANDO ALLAHYAR", "TANDO ALLAHYAR", "TANDO AHYAR"]


def test_fix_refuses_unexpected_row_count():
    fix = {"id": "X", "table": "t01", "province": "sindh", "match": {"name_admin_unit": "TANDO AHYAR"},
           "set": {"name_admin_unit": "TANDO ALLAHYAR"}, "expected_rows": 3}
    with pytest.raises(RuntimeError, match="matched 2 rows, expected 3"):
        apply_fixes({"t01": _table()}, [fix])


def _tehsil(shape_id, name, old):
    return {"shapeID": shape_id, "shapeName": name, "old_district": old, "geometry": box(0, 0, 1, 1)}


def test_assignment_rules():
    units = pd.DataFrame({
        "unit_name": ["SAHIWAL", "SAHIWAL", "CHICHAWATNI", "SILANWALI", "SAM RANI ZAI"],
        "district_id": ["pb_sahiwal", "pb_sargodha", "pb_sahiwal", "pb_sargodha", "kp_malakand"],
    })
    tehsils = [
        _tehsil("a", "CHICHAWATNI", "Sahiwal"),      # unique name
        _tehsil("b", "SAHIWAL", "Sahiwal"),          # shared name, old district decides
        _tehsil("c", "SAHIWAL", "Sargodha"),
        _tehsil("d", "SILANWALI", "Sargodha"),
        _tehsil("e", "SAM RANIZAI", "Malakand"),     # spacing differs
        _tehsil("f", "CHICHAWATNY", "Sahiwal"),      # typo -> fuzzy
        _tehsil("g", "NEW TEHSIL", "Sargodha"),      # unknown name, but only one successor
        _tehsil("h", "BAGH", "Azad Kashmir"),        # outside census tables
        _tehsil("i", "MYSTERY", "Sahiwal"),          # overridden by hand
    ]
    overrides = {"i": {"district_id": "pb_sargodha", "reason": "test"}}
    out = assign(tehsils, units, overrides).set_index("shape_id")
    assert out.loc["a", ["district_id", "method"]].tolist() == ["pb_sahiwal", "name"]
    assert out.loc["b", "district_id"] == "pb_sahiwal"
    assert out.loc["c", "district_id"] == "pb_sargodha"
    assert out.loc["e", ["district_id", "method"]].tolist() == ["kp_malakand", "name"]
    assert out.loc["f", ["district_id", "method"]].tolist() == ["pb_sahiwal", "name_fuzzy"]
    assert out.loc["g", ["district_id", "method"]].tolist() == ["pb_sargodha", "parent"]
    assert out.loc["h", ["district_id", "method"]].tolist() == ["ajk", "outside"]
    assert out.loc["i", ["district_id", "method"]].tolist() == ["pb_sargodha", "manual"]
