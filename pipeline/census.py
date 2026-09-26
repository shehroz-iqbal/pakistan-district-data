"""Step 2: load the raw census CSVs, apply documented fixes, build tables in DuckDB.

    python -m pipeline.census

Reads data/raw/census_2023/*.csv, applies config/fixes.yml, then runs sql/*.sql in
order against data/pakistan_districts.duckdb.
"""

from __future__ import annotations

import sys

import duckdb
import pandas as pd

from .common import CROSSWALKS, DB_PATH, PROVINCES, RAW, SQL_DIR, district_id, load_yaml, title_name

CENSUS_RAW = RAW / "census_2023"


def load_table(key: str, provinces: list[str]) -> pd.DataFrame:
    """Stack one census table across provinces, tagging each row with its origin."""
    frames = []
    for province in provinces:
        path = CENSUS_RAW / f"{key}_{province}.csv"
        frame = pd.read_csv(path, low_memory=False)
        frame.insert(0, "province_code", PROVINCES[province]["code"])
        frame.insert(1, "province_name", PROVINCES[province]["name"])
        frame["source_file"] = path.name
        frames.append(frame)

    columns = [set(f.columns) for f in frames]
    if any(c != columns[0] for c in columns):
        diff = set.union(*columns) - set.intersection(*columns)
        print(f"  note: {key} column sets differ across provinces: {sorted(diff)}")
    table = pd.concat(frames, ignore_index=True)
    # Names are matched exactly downstream, so strip stray whitespace once here.
    for col in ("name_admin_unit", "part_of_district", "admin_unit", "admin_units", "region"):
        if col in table.columns:
            table[col] = table[col].astype("string").str.strip()
    return table


def apply_fixes(tables: dict[str, pd.DataFrame], fixes: list[dict]) -> list[dict]:
    """Apply each fix and check it touched exactly the rows it expects."""
    log = []
    for fix in fixes:
        table = tables[fix["table"]]
        mask = table["province_code"] == PROVINCES[fix["province"]]["code"]
        for column, wanted in fix["match"].items():
            values = wanted if isinstance(wanted, list) else [wanted]
            mask &= table[column].isin(values)
        n = int(mask.sum())
        if n != fix["expected_rows"]:
            raise RuntimeError(
                f"Fix {fix['id']} matched {n} rows, expected {fix['expected_rows']}. "
                "The upstream file may have changed; review config/fixes.yml."
            )
        for column, value in fix["set"].items():
            table.loc[mask, column] = value
        log.append({"id": fix["id"], "table": fix["table"], "rows": n})
    return log


def catalog_frame() -> pd.DataFrame:
    rows = []
    for order, ind in enumerate(load_yaml("indicators.yml")):
        rows.append(
            {
                "indicator_id": ind["id"],
                "sort_order": order,
                "label": ind["label"],
                "theme": ind["theme"],
                "kind": ind["kind"],
                "numerator_col": ind.get("column") or ind.get("numerator"),
                "denominator_col": ind.get("denominator"),
                "multiplier": float(ind.get("multiplier", 1)),
                "years": float(ind.get("years", 0)) or None,
                "minuend": ind.get("minuend"),
                "subtrahend": ind.get("subtrahend"),
                "unit": ind["unit"],
                "decimals": int(ind["decimals"]),
                "direction": ind["direction"],
                "source_table": ind["source"],
                "definition": ind["definition"],
            }
        )
    return pd.DataFrame(rows)


def build(con: duckdb.DuckDBPyConnection | None = None) -> duckdb.DuckDBPyConnection:
    cfg = load_yaml("sources.yml")["census_2023"]
    provinces = cfg["provinces"]
    keys = list(cfg["district_tables"]) + list(cfg["tehsil_tables"])
    tables = {key: load_table(key, provinces) for key in keys}

    fix_log = apply_fixes(tables, load_yaml("fixes.yml"))
    for entry in fix_log:
        print(f"  fix {entry['id']}: {entry['rows']} rows in {entry['table']}")

    con = con or duckdb.connect(str(DB_PATH))
    con.create_function("district_id", district_id, ["VARCHAR", "VARCHAR"], "VARCHAR")
    con.create_function("title_name", title_name, ["VARCHAR"], "VARCHAR")

    for key, frame in tables.items():
        con.register(f"_{key}", frame)
        con.execute(f"CREATE OR REPLACE TABLE stg_{key} AS SELECT * FROM _{key}")
        con.unregister(f"_{key}")

    catalog = catalog_frame()
    con.register("_catalog", catalog)
    con.execute("CREATE OR REPLACE TABLE indicator_catalog AS SELECT * FROM _catalog")
    con.unregister("_catalog")

    map_units = pd.read_csv(CROSSWALKS / "map_units.csv")
    con.register("_map_units", map_units)
    con.execute("CREATE OR REPLACE TABLE ref_map_units AS SELECT * FROM _map_units")
    con.unregister("_map_units")

    fixes = pd.DataFrame(load_yaml("fixes.yml"))[["id", "table", "province", "expected_rows", "reason"]]
    con.register("_fixes", fixes)
    con.execute("CREATE OR REPLACE TABLE applied_fixes AS SELECT * FROM _fixes")
    con.unregister("_fixes")

    for sql_file in sorted(SQL_DIR.glob("*.sql")):
        con.execute(sql_file.read_text(encoding="utf-8"))
        print(f"  ran {sql_file.name}")

    n = con.execute("SELECT count(*) FROM dim_district").fetchone()[0]
    print(f"  {n} districts, {len(catalog)} indicators")
    return con


def main() -> int:
    print("census: building tables")
    build().close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
