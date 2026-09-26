# Data conventions

How data in this repository is stored, named, versioned and shared. These are the rules the
pipeline follows and the ones to follow when extending it.

## Storage: four layers, one direction

```
data/raw/        exact downloads, never edited          (not committed; rebuilt from the lock file)
     ↓ config/fixes.yml
DuckDB           working tables: stg_* → dim_* → cnt_* → indicator_values   (not committed)
     ↓
data/processed/  published files: CSV, Excel, GeoJSON, QA report           (committed)
     ↓
site/data/       what the dashboard loads                                  (committed)
```

Data only moves down. Nothing downstream is edited by hand: to change an output, change a
source pin, a fix, a crosswalk, an indicator definition or the SQL, and rebuild.

## Naming

- **Identifiers are stable; names are not.** `district_id` is the ISO 3166-2:PK province code
  plus the PBS spelling, lower-cased: `pb_dera_ghazi_khan`, `sd_tando_allahyar`. It is created
  once and never changes, even if a display name does. Join on IDs, never on names.
- **Names match through crosswalks.** When another source spells a place differently
  ("D.I.KHAN", "Qilla Abdullah", "Nawabshah"), the match is recorded in `crosswalks/` with a
  reason. Fuzzy matching only proposes; accepted matches are written down.
- **Columns** are `snake_case`. Counts use prefixes (`pop_` persons, `hh_` households) and sex
  suffixes (`_all`, `_male`, `_female`). `pbs_` marks a figure PBS itself published, kept only for
  cross-checks; `xchk_` marks a value loaded only to test another.
- **Files** are lower-case with underscores and say what one row is: `districts.csv` (one per
  district), `indicators_long.csv` (one per indicator per place).
- **SQL tables** use layer prefixes: `stg_` (raw, as loaded), `dim_` (entities), `cnt_` (counts),
  `ref_` (reference values used in checks).

## Versioning

- **Sources are pinned** to an upstream commit and a SHA-256 in `config/sources.lock.json`.
  Re-pinning (`python -m pipeline.fetch --lock`) is a deliberate, reviewable commit.
- **Corrections are versioned data** (`config/fixes.yml`), each with the number of rows it must
  touch, so a changed upstream file breaks the build instead of silently changing a number.
- **Builds are reproducible.** Two clean builds produce byte-identical text outputs (outputs
  are stamped with the date the sources were pinned, not the build date). CI rebuilds from
  scratch on every push and fails if the committed outputs differ from a fresh build.
- **Git history is the changelog.** A data release is a tag; the published files at that tag,
  the code that made them and the checks they passed travel together.

## Sharing

- **Formats for each audience.** CSV for analysts, an Excel workbook with a "Read me" sheet and
  plain-English column headings for colleagues who do not code, GeoJSON for GIS, and the
  dashboard for everyone else. All four come from the same build.
- **Every number is traceable** to a census table (`docs/data_dictionary.md`), a correction
  (`config/fixes.yml`) or a check (`data/processed/QA.md`).
- **Licences travel with the data** (`DATA_LICENSE.md`). Attribution to PBS, the CSV conversion
  and geoBoundaries is kept in every output format.

## Adding a source or an indicator

1. Add the source to `config/sources.yml`, run `python -m pipeline.fetch --lock`, commit the lock.
2. Load it in `pipeline/census.py` (or a new step) as a `stg_` table.
3. Join it to `dim_district` through a crosswalk if its names differ; record every
   non-obvious match.
4. Add its counts to `sql/02_district_counts.sql` and each indicator to `config/indicators.yml`.
   The indicator SQL, province and national aggregates, dashboard and data dictionary
   pick it up automatically.
5. Add at least one reconciliation check against a figure the publisher prints.
