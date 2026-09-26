"""Validation checks. Each returns a Check; `python -m pipeline.qa` writes them all
to data/processed/QA.md, and tests/test_checks.py fails the build if any fail.

Three kinds of evidence:
  reconciliation   our district-level sums reproduce figures PBS publishes
  identity         counts inside each table add up the way they must
  cross-table      tables that describe the same people agree with each other
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import duckdb
import pandas as pd

from .common import CROSSWALKS, PROCESSED, load_yaml


@dataclass
class Check:
    group: str
    name: str
    passed: bool
    detail: str


def _q(con, sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def district_structure(con) -> list[Check]:
    expected = {"PB": 36, "SD": 30, "KP": 35, "BA": 34, "IS": 1}
    got = dict(con.execute("SELECT province_code, count(*) FROM dim_district GROUP BY 1").fetchall())
    dupes = con.execute("SELECT count(*) - count(DISTINCT district_id) FROM dim_district").fetchone()[0]
    return [
        Check("structure", "136 districts, split by province as published", got == expected,
              ", ".join(f"{k} {got.get(k)}" for k in expected)),
        Check("structure", "district_id is unique", dupes == 0, f"{dupes} duplicates"),
    ]


def province_reconciliation(con) -> list[Check]:
    df = _q(con, """
        SELECT r.province_code,
               sum(c.pop_total) AS pop, any_value(r.pop_total) AS ref_pop,
               sum(c.area_km2) AS area, any_value(r.area_km2) AS ref_area,
               sum(c.pop_2017) AS pop17, any_value(r.pop_2017) AS ref_pop17
        FROM district_counts c JOIN ref_province_totals r USING (province_code)
        GROUP BY r.province_code ORDER BY 1""")
    out = []
    for col, label in [("pop", "population 2023"), ("area", "area"), ("pop17", "population 2017")]:
        diff = (df[col] - df[f"ref_{col}"]).abs()
        out.append(Check("reconciliation", f"Districts sum to PBS province totals: {label}",
                         bool((diff == 0).all()),
                         "exact in all 5" if (diff == 0).all() else df[diff > 0].to_string()))
    return out


def national_headlines(con) -> list[Check]:
    ref = load_yaml("reference_figures.yml")["national"]
    nat = dict(con.execute("SELECT indicator_id, value FROM indicator_values WHERE level='national'").fetchall())
    num = dict(con.execute("SELECT indicator_id, numerator FROM indicator_values WHERE level='national'").fetchall())
    ours = {
        **{k: nat[k] for k in ("growth_rate", "urban_share", "sex_ratio", "density", "literacy_rate",
                               "literacy_rate_male", "literacy_rate_female", "out_of_school_rate",
                               "out_of_school_rate_male", "out_of_school_rate_female")},
        "population_millions": nat["population"] / 1e6,
        "population_2017_millions": nat["population_2017"] / 1e6,
        "urban_population_millions": num["urban_share"] / 1e6,
    }
    # PBS prints millions to two decimals, sometimes truncated (241,499,431 -> 241.49),
    # so counts in millions get a tolerance of one unit in the last digit.
    labels = {
        "population_millions": "Population (millions)",
        "population_2017_millions": "Population 2017 (millions)",
        "growth_rate": "Annual growth 2017-23 (%)",
        "urban_population_millions": "Urban population (millions)",
        "urban_share": "Urban share (%)",
        "sex_ratio": "Sex ratio",
        "density": "Density (per km2)",
        "literacy_rate": "Literacy rate 10+ (%)",
        "literacy_rate_male": "Male literacy (%)",
        "literacy_rate_female": "Female literacy (%)",
        "out_of_school_rate": "Out of school 5-16 (%)",
        "out_of_school_rate_male": "Out of school 5-16, boys (%)",
        "out_of_school_rate_female": "Out of school 5-16, girls (%)",
    }
    out = []
    for key, label in labels.items():
        tol = 0.01 if key.endswith("_millions") else 0.005
        out.append(Check("reconciliation", f"Reproduces PBS national figure: {label}",
                         abs(ours[key] - ref[key]) <= tol, f"ours {ours[key]:,.3f} vs PBS {ref[key]:,.2f}"))
    prov = dict(con.execute("SELECT geo_id, value FROM indicator_values "
                            "WHERE level='province' AND indicator_id='population'").fetchall())
    for code, millions in load_yaml("reference_figures.yml")["province_population_millions"].items():
        ours = prov[code] / 1e6
        out.append(Check("reconciliation", f"Reproduces PBS province population: {code}",
                         abs(ours - millions) <= 0.01, f"ours {ours:.3f}m vs PBS {millions:.2f}m"))
    return out


def identities(con) -> list[Check]:
    rules = {
        "Men + women + transgender = total (Table 1)":
            "pop_male + pop_female + pop_transgender = pop_total",
        "Urban + rural = total (Table 1)": "pop_urban + pop_rural = pop_total",
        "Lighting sources add up to households (Table 22)":
            "hh_light_electric + hh_light_solar + hh_light_other = households",
        "Cooking fuels add up to households (Table 22)":
            "hh_fuel_gas + hh_fuel_lpg + hh_fuel_firewood + hh_fuel_other = households",
        "Toilet types add up to households (Table 24)":
            "hh_toilet_flush + hh_toilet_non_flush + hh_toilet_none = households_t24",
        "Owner's sex covers owned + rented + rent-free dwellings (Table 25)":
            "owner_any = hh_owned + hh_rented + hh_rent_free",
        "Structure types add up to households (Table 20)":
            "hh_pakka + hh_semi_pakka + hh_kacha = households_t20",
        "Literate 10+ never exceeds population 10+ (Table 12)": "literate10_all <= pop10_all",
        "Out-of-school children never exceed children 5-16 (Tables 12, 13b)": "oosc_all <= pop5_16_all",
    }
    out = []
    for label, rule in rules.items():
        bad = _q(con, f"SELECT district_id FROM district_counts WHERE NOT ({rule}) OR ({rule}) IS NULL")
        out.append(Check("identity", label, bad.empty,
                         "holds in all 136 districts" if bad.empty else ", ".join(bad.district_id)))
    return out


def cross_table(con) -> list[Check]:
    hh = _q(con, """SELECT district_id FROM district_counts
                    WHERE NOT (households = households_t20 AND households = households_t23
                               AND households = households_t24 AND households = households_t25)""")
    x13 = _q(con, """SELECT count(*) AS both, count(*) FILTER (WHERE xchk_pop5_16_all_t13a <> pop5_16_all) AS differ
                     FROM district_counts WHERE xchk_pop5_16_all_t13a IS NOT NULL""").iloc[0]
    derived = _q(con, """
        SELECT
          max(abs(pop_total / area_km2 - pbs_density))                 AS density,
          max(abs(100 * pop_urban / pop_total - pbs_urban_share))      AS urban,
          max(abs(100 * pop_male / pop_female - pbs_sex_ratio))        AS sex_ratio,
          max(abs(100 * literate10_all / pop10_all - pbs_literacy_rate)) AS literacy,
          max(abs(100 * (power(pop_total / pop_2017, 1 / 6) - 1) - pbs_growth_rate)) AS growth
        FROM district_counts""").iloc[0]
    return [
        Check("cross-table", "Tables 20, 22, 23, 24 and 25 report the same households", hh.empty,
              "identical in all 136 districts" if hh.empty else ", ".join(hh.district_id)),
        Check("cross-table", "Tables 13a and 13b agree on the 5-16 population", int(x13["differ"]) == 0,
              f"{int(x13['both'])} districts have both; {int(x13['differ'])} differ"),
        Check("cross-table", "Recomputed density matches PBS (within 0.5)", derived["density"] <= 0.5,
              f"largest gap {derived['density']:.3f}"),
        Check("cross-table", "Recomputed urban share matches PBS (within 0.05 pts)", derived["urban"] <= 0.05,
              f"largest gap {derived['urban']:.3f}"),
        Check("cross-table", "Recomputed sex ratio matches PBS (within 0.05)", derived["sex_ratio"] <= 0.05,
              f"largest gap {derived['sex_ratio']:.3f}"),
        Check("cross-table", "Recomputed literacy matches PBS 'Literate %' (within 0.05 pts)",
              derived["literacy"] <= 0.05, f"largest gap {derived['literacy']:.3f}"),
        Check("cross-table", "Recomputed growth rate matches PBS (within 0.03 pts)", derived["growth"] <= 0.03,
              f"largest gap {derived['growth']:.3f} (PBS uses the exact intercensal interval; we use 6 years)"),
    ]


def ranges_and_completeness(con) -> list[Check]:
    pct = _q(con, """SELECT v.indicator_id, v.geo_id, v.value FROM indicator_values v
                     JOIN indicator_catalog c USING (indicator_id)
                     WHERE c.unit LIKE '%\\%%' ESCAPE '\\' AND (v.value < 0 OR v.value > 100)""")
    nulls = _q(con, "SELECT indicator_id, geo_id FROM indicator_values WHERE value IS NULL")
    return [
        Check("completeness", "Every indicator has a value for every district, province and Pakistan",
              nulls.empty, f"{len(nulls)} missing"),
        Check("completeness", "Every percentage lies between 0 and 100", pct.empty, f"{len(pct)} out of range"),
    ]


def geometry(con) -> list[Check]:
    path = PROCESSED / "districts_2023.geojson"
    features = json.loads(path.read_text())["features"]
    mapped = {d for f in features for d in f["properties"]["district_ids"]}
    districts = {r[0] for r in con.execute("SELECT district_id FROM dim_district").fetchall()}
    assignment = pd.read_csv(CROSSWALKS / "generated" / "tehsil_assignment.csv")
    area = pd.read_csv(PROCESSED / "qa_district_area_check.csv")
    within = int(((area["ratio"] - 1).abs() <= 0.10).sum())
    return [
        Check("geometry", "Every district is drawn on the map", mapped == districts,
              f"{len(mapped)} of {len(districts)} districts in {len(features)} shapes"),
        Check("geometry", "Every tehsil polygon is assigned exactly once",
              assignment["district_id"].notna().all() and assignment["shape_id"].is_unique,
              f"{len(assignment)} polygons: " + ", ".join(
                  f"{k} {v}" for k, v in assignment["method"].value_counts().items())),
        Check("geometry", "Mapped areas track PBS areas (median ratio within 5%)",
              abs(area["ratio"].median() - 1) <= 0.05,
              f"median {area['ratio'].median():.3f}; {within} of {len(area)} shapes within 10%"),
    ]


def run_all(con: duckdb.DuckDBPyConnection) -> list[Check]:
    checks: list[Check] = []
    for fn in (district_structure, province_reconciliation, national_headlines,
               identities, cross_table, ranges_and_completeness, geometry):
        checks.extend(fn(con))
    return checks
