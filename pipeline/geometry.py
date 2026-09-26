"""Step 3: build 2023 district boundaries by dissolving tehsil polygons.

    python -m pipeline.geometry

No open boundary file matches the 2023 census districts: geoBoundaries' district
layer is an older vintage (126 units, no Chiniot, Nankana Sahib, Sujawal, the
seven Karachi districts, ...). Its tehsil layer (554 units, derived from PBS census
maps) is fine-grained enough to rebuild them. Each tehsil polygon is assigned to a
2023 district by the first rule that applies:

  manual        crosswalks/tehsil_overrides.csv (reviewed by hand, each with a reason)
  outside       it lies in Azad Jammu & Kashmir or Gilgit-Baltistan, which the PBS
                census tables do not cover (drawn grey, for context)
  name          its name is a census 2023 sub-district unit found in one district only,
                or in several of which exactly one fits the older district it sits in
  name_cross_parent
                a unique name match that disagrees with the older district
                (kept, but flagged for review in the assignment table)
  name_fuzzy    a close spelling that fits the older district
  parent        no name match, but its older district became exactly one 2023 district

Anything left over stops the build. Districts grouped in crosswalks/map_units.csv
(Karachi's seven) are drawn as one shape. Shapes are checked against the areas PBS
reports, simplified as a coverage (shared borders stay shared) and written to
data/processed.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict

import duckdb
import pandas as pd
import shapely
from pyproj import Geod
from rapidfuzz import fuzz, process
from shapely.geometry import mapping, shape

from .common import CROSSWALKS, DB_PATH, PROCESSED, RAW, match_key

OVERRIDES = CROSSWALKS / "tehsil_overrides.csv"
ASSIGNMENT_OUT = CROSSWALKS / "generated" / "tehsil_assignment.csv"
AREA_CHECK_OUT = PROCESSED / "qa_district_area_check.csv"

# Old (geoBoundaries ADM2) districts outside the scope of the PBS census tables.
OUTSIDE_SCOPE = {
    "Azad Kashmir": ("ajk", "Azad Jammu & Kashmir"),
    "Astore": ("gb", "Gilgit-Baltistan"),
    "Diamer": ("gb", "Gilgit-Baltistan"),
    "Ghanche": ("gb", "Gilgit-Baltistan"),
    "Ghizer": ("gb", "Gilgit-Baltistan"),
    "Gilgit": ("gb", "Gilgit-Baltistan"),
    "Hunza": ("gb", "Gilgit-Baltistan"),
    "Kharmang": ("gb", "Gilgit-Baltistan"),
    "Nagar": ("gb", "Gilgit-Baltistan"),
    "Shigar": ("gb", "Gilgit-Baltistan"),
    "Skardu": ("gb", "Gilgit-Baltistan"),
}

OUTSIDE_NAMES = {"ajk": "Azad Jammu & Kashmir", "gb": "Gilgit-Baltistan"}

FUZZY_MIN = 88  # rapidfuzz ratio (0-100) on space-free names; lower lets wrong pairs through
GEOD = Geod(ellps="WGS84")


def load_polygons(path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for feature in data["features"]:
        geom = shapely.make_valid(shape(feature["geometry"]))
        out.append({**feature["properties"], "geometry": geom})
    return out


def old_district_of(tehsils: list[dict], districts: list[dict]) -> None:
    """Tag each tehsil with the older ADM2 district containing most of it."""
    tree = shapely.STRtree([d["geometry"] for d in districts])
    for t in tehsils:
        candidates = tree.query(t["geometry"], predicate="intersects")
        best, best_area = None, 0.0
        for idx in candidates:
            area = t["geometry"].intersection(districts[idx]["geometry"]).area
            if area > best_area:
                best, best_area = districts[idx]["shapeName"], area
        t["old_district"] = best


def load_overrides() -> dict[str, dict]:
    if not OVERRIDES.exists():
        return {}
    with open(OVERRIDES, encoding="utf-8") as fh:
        return {row["shape_id"]: row for row in csv.DictReader(fh)}


def compact(key: str) -> str:
    """'SAM RANI ZAI' and 'SAM RANIZAI' should meet: compare without spaces."""
    return key.replace(" ", "")


def assign(tehsils: list[dict], units: pd.DataFrame, overrides: dict[str, dict]) -> pd.DataFrame:
    """Decide which 2023 district each tehsil polygon belongs to."""
    districts_by_key: dict[str, set[str]] = defaultdict(set)
    for name, district in zip(units["unit_name"], units["district_id"]):
        districts_by_key[compact(match_key(name))].add(district)
    all_keys = list(districts_by_key)

    # Pass 1: names that exist in exactly one 2023 district are unambiguous. They
    # also teach us which 2023 districts each older district turned into.
    old_to_new: dict[str, Counter] = defaultdict(Counter)
    for t in tehsils:
        t["key"] = compact(match_key(t["shapeName"]))
        exact = districts_by_key.get(t["key"], set())
        if len(exact) == 1:
            old_to_new[t["old_district"]][next(iter(exact))] += 1

    rows = []
    for t in tehsils:
        old = t["old_district"]
        consistent = set(old_to_new.get(old, {}))
        exact = districts_by_key.get(t["key"], set())
        row = {
            "shape_id": t["shapeID"],
            "shape_name": t["shapeName"],
            "old_district": old,
            "district_id": None,
            "method": None,
            "matched_unit": None,
            "score": None,
        }

        if t["shapeID"] in overrides:
            ov = overrides[t["shapeID"]]
            row.update(district_id=ov["district_id"], method="manual", matched_unit=ov["reason"])
        elif old in OUTSIDE_SCOPE:
            row.update(district_id=OUTSIDE_SCOPE[old][0], method="outside")
        elif len(exact) == 1:
            # A unique name beats the old-district hint (the older layer's borders
            # are rough), but we record when the two disagree so it can be reviewed.
            district = next(iter(exact))
            method = "name" if district in consistent else "name_cross_parent"
            row.update(district_id=district, method=method, matched_unit=t["key"], score=100)
        elif len(exact & consistent) == 1:
            # Same name in several districts (e.g. SAHIWAL): the old district decides.
            row.update(district_id=(exact & consistent).pop(), method="name",
                       matched_unit=t["key"], score=100)
        else:
            # Fuzzy: best-scoring census unit name whose district is consistent.
            for key, score, _ in process.extract(t["key"], all_keys, scorer=fuzz.ratio, limit=5):
                hits = districts_by_key[key] & consistent
                if score >= FUZZY_MIN and len(hits) == 1:
                    row.update(district_id=hits.pop(), method="name_fuzzy",
                               matched_unit=key, score=round(score))
                    break
            else:
                if len(consistent) == 1:
                    row.update(district_id=next(iter(consistent)), method="parent")
        rows.append(row)
    return pd.DataFrame(rows)


def geodesic_km2(geom) -> float:
    area, _ = GEOD.geometry_area_perimeter(shapely.orient_polygons(geom))
    return abs(area) / 1e6


def build() -> int:
    tehsils = load_polygons(RAW / "geoboundaries" / "adm3.geojson")
    old_districts = load_polygons(RAW / "geoboundaries" / "adm2.geojson")
    old_district_of(tehsils, old_districts)

    con = duckdb.connect(str(DB_PATH))
    units = con.execute("SELECT unit_name, district_id FROM dim_subdistrict").df()
    dims = con.execute(
        "SELECT district_id, district_name, province_code, province_name, map_unit_id, map_unit_name FROM dim_district"
    ).df()
    census_area = dict(con.execute("SELECT district_id, area_km2 FROM cnt_t01").fetchall())
    con.close()

    table = assign(tehsils, units, load_overrides())
    ASSIGNMENT_OUT.parent.mkdir(parents=True, exist_ok=True)
    table.sort_values(["district_id", "shape_name", "shape_id"], na_position="first").to_csv(
        ASSIGNMENT_OUT, index=False)

    unresolved = table[table["district_id"].isna()]
    if len(unresolved):
        print(f"geometry: {len(unresolved)} tehsil polygons could not be assigned:")
        print(unresolved[["shape_id", "shape_name", "old_district"]].to_string(index=False))
        print(f"Add them to {OVERRIDES.relative_to(OVERRIDES.parents[1])} and re-run.")
        return 1

    known = set(dims["district_id"]) | {"ajk", "gb"}
    bad = set(table["district_id"]) - known
    if bad:
        print(f"geometry: overrides point at unknown district_ids: {sorted(bad)}")
        return 1
    missing = set(dims["district_id"]) - set(table["district_id"])
    if missing:
        print(f"geometry: no polygons for districts: {sorted(missing)}")
        return 1

    # Dissolve tehsils into map units (a district, or a group such as Karachi).
    to_unit = dict(zip(dims["district_id"], dims["map_unit_id"]))
    to_unit.update({"ajk": "ajk", "gb": "gb"})
    table["map_unit_id"] = table["district_id"].map(to_unit)
    geom_by_id = {t["shapeID"]: t["geometry"] for t in tehsils}
    groups = table.groupby("map_unit_id")["shape_id"].apply(list)
    ids = list(groups.index)
    dissolved = [shapely.union_all([geom_by_id[s] for s in groups[i]]) for i in ids]

    # Area check: mapped (geodesic) area against the area PBS reports.
    members = dims.groupby("map_unit_id")["district_id"].apply(list)
    checks = []
    for i, geom in zip(ids, dissolved):
        if i in ("ajk", "gb"):
            continue
        reported = sum(census_area[d] for d in members[i])
        gis = geodesic_km2(geom)
        checks.append({
            "map_unit_id": i,
            "districts": len(members[i]),
            "area_reported_km2": reported,
            "area_mapped_km2": round(gis, 1),
            "ratio": round(gis / reported, 3),
            "assignment_methods": ",".join(sorted(set(table.loc[table.map_unit_id == i, "method"]))),
        })
    checks = pd.DataFrame(checks).sort_values(["ratio", "map_unit_id"])
    checks.to_csv(AREA_CHECK_OUT, index=False)

    # Simplify as a coverage so neighbouring shapes keep identical borders.
    simplified = shapely.coverage_simplify(dissolved, tolerance=0.01)
    # RFC 7946 winding (outer rings counter-clockwise), coordinates to ~10 m.
    simplified = [shapely.orient_polygons(shapely.set_precision(g, 0.0001)) for g in simplified]

    meta = dims.drop_duplicates("map_unit_id").set_index("map_unit_id")
    features = []
    for i, geom in zip(ids, simplified):
        if i in ("ajk", "gb"):
            props = {"map_unit_id": i, "name": OUTSIDE_NAMES[i], "province_code": None,
                     "district_ids": [], "in_census_tables": False}
        else:
            props = {"map_unit_id": i, "name": meta.at[i, "map_unit_name"],
                     "province_code": meta.at[i, "province_code"],
                     "district_ids": members[i], "in_census_tables": True}
        features.append({"type": "Feature", "properties": props, "geometry": mapping(geom)})

    out = PROCESSED / "districts_2023.geojson"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh, separators=(",", ":"))

    # Province outlines for the map, dissolved from the simplified shapes so they
    # line up exactly with the district borders.
    province_of = {i: (meta.at[i, "province_code"] if i in meta.index else i) for i in ids}
    province_names = dict(zip(dims["province_code"], dims["province_name"])) | OUTSIDE_NAMES
    by_province: dict[str, list] = defaultdict(list)
    for i, geom in zip(ids, simplified):
        by_province[province_of[i]].append(geom)
    province_features = [
        {"type": "Feature",
         "properties": {"province_code": code, "name": province_names[code]},
         "geometry": mapping(shapely.orient_polygons(shapely.set_precision(shapely.union_all(geoms), 0.0001)))}
        for code, geoms in sorted(by_province.items())
    ]
    with open(PROCESSED / "provinces_2023.geojson", "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": province_features}, fh, separators=(",", ":"))

    counts = table["method"].value_counts().to_dict()
    ratio = checks["ratio"]
    print(f"geometry: {len(table)} tehsil polygons -> {len(ids)} map units; methods {counts}")
    print(f"geometry: mapped area / PBS area median {ratio.median():.3f}; "
          f"{(abs(ratio - 1) <= 0.10).sum()} of {len(checks)} within 10%")
    print(f"geometry: wrote {out.relative_to(PROCESSED.parents[1])} ({out.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(build())
