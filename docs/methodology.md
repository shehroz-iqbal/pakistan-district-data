# Methodology

This document explains how the published files are built, what was corrected on the way,
and where the results are approximate. The code is the final word; each section
names the file that does the work.

## 1. Sources

| Source | What it provides | Pinned to | Licence |
|---|---|---|---|
| [PBS, 7th Population and Housing Census 2023](https://www.pbs.gov.pk/digital-census/detailed-results), district tables | Every number in the dataset | PBS publishes PDFs | Official statistics, attributed |
| [Fahad Mirza, `pakistan_census_2023_tables`](https://github.com/fahad-mirza/pakistan_census_2023_tables) | The same tables converted from PDF to CSV | commit `887d710` | MIT |
| [geoBoundaries](https://www.geoboundaries.org/) gbOpen, Pakistan ADM3 (tehsils) | Polygons the district shapes are built from | commit `5c25134` | ODbL 1.0 |
| geoBoundaries gbOpen, Pakistan ADM2 (older districts) | A hint for matching tehsils to districts | commit `5c25134` | Public domain |

`config/sources.yml` lists every file; `config/sources.lock.json` holds its URL and SHA-256.
`python -m pipeline.fetch` refuses any download whose checksum has changed, so an upstream
edit can never flow into the outputs unreviewed.

**Tables used.** Table 1 (area, population, sex, urban/rural, growth), 12 (literacy and
out-of-school children), 13b (population aged 5-16), 16 (disability), 20 (structure type),
22 (lighting, cooking fuel), 23 (drinking water), 24 (toilets) and 25 (tenure, owner's sex,
rooms). Table 13a is loaded only to cross-check 13b.

## 2. Corrections to the source files

The raw CSVs are never edited. Corrections are data, in `config/fixes.yml`: each one names
the rows it matches, what it changes, why, and how many rows it must touch. The build stops
if that count changes, so a fix can't silently vanish or double-apply after an upstream update.

| Fix | Problem | How it was found |
|---|---|---|
| F001-F003 | Table 1 spells Tando Allahyar "TANDO AHYAR"; every other table spells it correctly, so the district fell out of every join. | District names differed between tables. |
| F004-F005 | Table 1 lists the Tando Muhammad Khan *taluka* (263 km², 272,427 people) as a second *district* row. | Sindh's districts summed to exactly 272,427 more people and 263 km² more area than the Sindh province row. The district total (726,119) equals its three talukas: Bulri Shah Karim 247,027 + Tando Ghulam Hyder 206,665 + 272,427. |
| Table 13a | 143 cells are blank, every one a value above one million; for the 5-16 population that hits Lahore, Faisalabad, Rawalpindi and 12 more districts. | The out-of-school rate came out blank for 15 districts. Table 13b carries the same rows intact, and every count the two tables share agrees (they differ only in how many decimals "Literate %" is printed with), so 13b is used. |

Without these corrections Pakistan's population would be overstated by 272,427 and the
out-of-school rate could not be computed for 15 districts.

## 3. From tables to indicators

`pipeline/census.py` loads the CSVs into DuckDB and applies the fixes; `sql/` does the rest.

1. **`01_dim_district.sql`** takes the 136 district rows of Table 1 as the master list and
   gives each a stable `district_id` (see `docs/conventions.md`).
2. **`02_district_counts.sql`** pivots each table into one row per district, one column per
   count: `district_counts`. Blank cells in the PDFs mean zero, but a blank is only turned
   into 0 where the table's own totals prove it (one case: Orakzai's "no toilet" count, where
   flush + non-flush toilets already equal all households).
3. **`03_indicators.sql`** computes every indicator in `config/indicators.yml` for districts,
   Karachi (as one unit), provinces and Pakistan in a single `GROUPING SETS` query.

Two rules matter for correctness:

- **Aggregates are rebuilt from counts.** Punjab's literacy rate is literate people in all 36
  districts divided by all people aged 10+ in those districts. It is never an average of 36
  district rates, which would weight Lahore (13 million people) the same as Chiniot.
- **Numerator and denominator always come from the same table.** The detailed tables (12, 13,
  16) cover 240,458,089 people against Table 1's 241,499,431: 0.43% fewer nationally, but up to
  15.5% fewer in Kolai Palas Kohistan and 12.5% in Quetta. Mixing a Table 12 numerator with a
  Table 1 denominator would understate literacy there, so rates are always computed within a
  table.

## 4. Validation

`pipeline/checks.py` defines 44 checks; `python -m pipeline.qa` writes the results to
`data/processed/QA.md` and `pytest` fails the build if any fail. They fall into five groups:

- **Reconciliation.** District sums equal PBS's province rows exactly (population, area,
  2017 population), and the pipeline reproduces 13 of PBS's published national figures (e.g.
  literacy 60.65%, female literacy 52.84%, out-of-school children 35.60%, urban share 38.88%)
  and all five province populations.
- **Identity.** Counts inside each table add up (men + women + transgender = total; lighting
  sources, cooking fuels, toilet types and structure types each sum to households; owner's sex
  covers owned + rented + rent-free dwellings), in all 136 districts.
- **Cross-table.** Tables 20, 22, 23, 24 and 25 report identical household counts; tables 13a
  and 13b agree; our recomputed density, urban share, sex ratio and literacy match the figures
  PBS prints in the same tables.
- **Completeness.** Every indicator has a value everywhere; every percentage is within 0-100.
- **Geometry.** Every district is drawn and every tehsil polygon is used exactly once.

**Documented differences, not errors.** Growth rates we recompute over exactly six years
differ from PBS's by up to 0.03 points (PBS appears to use the exact intercensal interval).
Tables 22-25 sum to 38.29 million households against PBS's headline 38.32 million, so persons
per household is 6.31 here against PBS's 6.33.

## 5. District boundaries

No open boundary file matches the 2023 census districts. geoBoundaries' district layer is an
older vintage (126 units: no Chiniot, Nankana Sahib, Sujawal, Torghar or the seven Karachi
districts). Its tehsil layer (554 units, derived from PBS census maps) is fine-grained enough
to rebuild them, so `pipeline/geometry.py` assigns every tehsil polygon to a 2023 district and
dissolves them:

| Rule, in order | Polygons |
|---|---|
| **manual**: listed in `crosswalks/tehsil_overrides.csv`, each with a reason | 27 |
| **name**: its name matches a census 2023 sub-district unit (tehsil, taluka, sub-division) | 426 |
| **name_fuzzy**: a close spelling (e.g. "Hassanabdal" / "Hasanabdal"), accepted only if consistent with the old district it sits in | 37 |
| **parent**: no name match, but its old district became exactly one 2023 district | 26 |
| **outside**: in Azad Jammu & Kashmir or Gilgit-Baltistan, which these PBS tables do not cover | 38 |

The manual overrides are mostly places the automatic rules can't know about: former Frontier
Regions merged into settled districts in 2018 (FR Bannu into Bannu, FR Kohat into Kohat, ...),
tehsils that moved between districts, and Karachi. Every polygon's assignment and method is
written to `crosswalks/generated/tehsil_assignment.csv` for review.

**Checking the result.** Each rebuilt shape's geodesic area is compared with the area PBS
reports (`data/processed/qa_district_area_check.csv`). The median ratio is 1.003 and 103 of
130 shapes are within 10%. The larger gaps are concentrated in Balochistan (16 of the 27),
where districts were redrawn below the tehsil level after the boundary data was made, and
where PBS's reported areas are themselves sometimes implausible (Surab is reported as 762 km²).
Those shapes are approximate.

**Karachi.** The tehsil layer divides Karachi into 2017-era towns, which do not line up with
the 2023 districts (a rebuilt Karachi West came out at 6% of its reported area). The seven
districts are therefore drawn as one shape (`crosswalks/map_units.csv`); its outline is
accurate (area within 4% of the reported total) and each district keeps its own row in the data.

## 6. Limitations and next steps

- Boundaries in parts of Balochistan and within Karachi are approximate (see above). A 2023
  boundary source (for example OCHA's COD-AB with P-codes) would fix both and give a P-code
  crosswalk for joining humanitarian datasets.
- Azad Jammu & Kashmir and Gilgit-Baltistan are outside these tables.
- Only 10 of the census tables are used. Age structure (Tables 5-8), religion (9), language
  (11) and tehsil-level results are natural extensions; so are survey sources such as PSLM or
  the Labour Force Survey, joined on `district_id`.
