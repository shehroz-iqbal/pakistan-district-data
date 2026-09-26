-- dim_district: one row per 2023 census district (136 after corrections).
--
-- Identity comes from Table 1 because it is the headline table and the only one
-- with province totals to reconcile against. district_id is derived from the
-- PBS spelling (e.g. pb_dera_ghazi_khan) and never changes once published.

CREATE OR REPLACE TABLE dim_district AS
WITH districts AS (
    SELECT
        district_id(province_code, name_admin_unit) AS district_id,
        title_name(name_admin_unit)                 AS district_name,
        name_admin_unit                             AS census_name,
        province_code,
        province_name
    FROM stg_t01
    WHERE admin_unit = 'DISTRICT'
      AND region = 'OVERALL'
)
SELECT
    d.*,
    -- Map units: the shape a district is drawn as. Normally the district itself;
    -- crosswalks/map_units.csv groups districts whose borders can't be drawn reliably.
    coalesce(m.map_unit_id, d.district_id)     AS map_unit_id,
    coalesce(m.map_unit_name, d.district_name) AS map_unit_name
FROM districts AS d
LEFT JOIN ref_map_units AS m USING (district_id)
ORDER BY d.province_code, d.district_name;

-- Sub-district units (tehsils, talukas, sub-divisions) with their parent district.
-- Used by the geometry step to assign tehsil polygons to 2023 districts.
CREATE OR REPLACE TABLE dim_subdistrict AS
SELECT
    s.name_admin_unit AS unit_name,
    s.admin_unit      AS unit_type,
    d.district_id,
    s.all_sexes       AS population,
    s.area_sqkm       AS area_km2
FROM stg_t01_all AS s
JOIN dim_district AS d
  ON d.province_code = s.province_code
 AND d.census_name   = s.part_of_district
WHERE s.admin_unit NOT IN ('PROVINCE', 'DISTRICT', 'DIVISION')
  AND s.region = 'OVERALL';

-- Province totals exactly as PBS prints them (Islamabad has no province row, so
-- its single district stands in). Used only for reconciliation tests.
CREATE OR REPLACE TABLE ref_province_totals AS
SELECT province_code, all_sexes AS pop_total, area_sqkm AS area_km2, pop_2017
FROM stg_t01_all
WHERE admin_unit = 'PROVINCE' AND region = 'OVERALL'
UNION ALL
SELECT province_code, all_sexes, area_sqkm, pop_2017
FROM stg_t01
WHERE province_code = 'IS' AND admin_unit = 'DISTRICT' AND region = 'OVERALL';
