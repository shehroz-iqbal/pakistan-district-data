-- district_counts: one row per district, one column per count taken from the
-- census tables. Every published indicator is a sum or ratio of these columns,
-- which is what lets province and national figures be rebuilt from districts.
--
-- Naming: pop_* = persons, hh_* = households, *_all/_male/_female = sex.
-- Blank cells in the PDFs mean zero; we only turn them into 0 where the table's
-- own totals prove it (see hh_toilet_none).

-- Table 1: headline counts, plus PBS's own derived figures for cross-checks.
CREATE OR REPLACE TABLE cnt_t01 AS
SELECT
    d.district_id,
    max(s.area_sqkm)                      FILTER (WHERE s.region = 'OVERALL') AS area_km2,
    max(s.all_sexes)                      FILTER (WHERE s.region = 'OVERALL') AS pop_total,
    max(s.male)                           FILTER (WHERE s.region = 'OVERALL') AS pop_male,
    max(s.female)                         FILTER (WHERE s.region = 'OVERALL') AS pop_female,
    coalesce(max(s.tgend)                 FILTER (WHERE s.region = 'OVERALL'), 0) AS pop_transgender,
    coalesce(max(s.all_sexes)             FILTER (WHERE s.region = 'URBAN'), 0)   AS pop_urban,
    coalesce(max(s.all_sexes)             FILTER (WHERE s.region = 'RURAL'), 0)   AS pop_rural,
    max(s.pop_2017)                       FILTER (WHERE s.region = 'OVERALL') AS pop_2017,
    max(s.avg_annual_gr_rate_17_23)       FILTER (WHERE s.region = 'OVERALL') AS pbs_growth_rate,
    max(s.avg_hh_size)                    FILTER (WHERE s.region = 'OVERALL') AS pbs_household_size,
    max(s.urban_prop)                     FILTER (WHERE s.region = 'OVERALL') AS pbs_urban_share,
    max(s.pop_den_sqkm)                   FILTER (WHERE s.region = 'OVERALL') AS pbs_density,
    max(s.sex_ratio)                      FILTER (WHERE s.region = 'OVERALL') AS pbs_sex_ratio
FROM stg_t01 AS s
JOIN dim_district AS d
  ON d.province_code = s.province_code AND d.census_name = s.name_admin_unit
WHERE s.admin_unit = 'DISTRICT'
GROUP BY d.district_id;

-- Table 12: literacy (age 10+) and out-of-school children (age 5-16).
CREATE OR REPLACE TABLE cnt_t12 AS
SELECT
    d.district_id,
    max(s.all_sexes_overall) FILTER (WHERE s.vars = 'Population >=10')               AS pop10_all,
    max(s.male_overall)      FILTER (WHERE s.vars = 'Population >=10')               AS pop10_male,
    max(s.female_overall)    FILTER (WHERE s.vars = 'Population >=10')               AS pop10_female,
    max(s.all_sexes_overall) FILTER (WHERE s.vars = 'Literate >=10')                 AS literate10_all,
    max(s.male_overall)      FILTER (WHERE s.vars = 'Literate >=10')                 AS literate10_male,
    max(s.female_overall)    FILTER (WHERE s.vars = 'Literate >=10')                 AS literate10_female,
    max(s.all_sexes_overall) FILTER (WHERE s.vars = 'Literate %')                    AS pbs_literacy_rate,
    max(s.all_sexes_overall) FILTER (WHERE s.vars = 'Never to School (5-16)')        AS never_school_all,
    max(s.all_sexes_overall) FILTER (WHERE s.vars = 'Drop Out (5 - 16)')             AS dropout_all,
    max(s.all_sexes_overall) FILTER (WHERE s.vars = 'Out of School Children (5-16)') AS oosc_all,
    max(s.male_overall)      FILTER (WHERE s.vars = 'Out of School Children (5-16)') AS oosc_male,
    max(s.female_overall)    FILTER (WHERE s.vars = 'Out of School Children (5-16)') AS oosc_female
FROM stg_t12 AS s
JOIN dim_district AS d
  ON d.province_code = s.province_code AND d.census_name = s.name_admin_unit
WHERE s.admin_unit = 'DISTRICT'
GROUP BY d.district_id;

-- Table 13b: the age 5-16 population that the out-of-school counts refer to.
-- Table 13a carries the same rows, but its conversion left 143 cells blank, all of
-- them values above one million (Lahore, Faisalabad, Rawalpindi, ...). 13b is complete,
-- so it is the source; 13a is kept only so tests can confirm the two agree.
CREATE OR REPLACE TABLE cnt_t13 AS
WITH b AS (
    SELECT
        d.district_id,
        max(s.all_sexes_overall) FILTER (WHERE s.vars = 'Population' AND s.age_bracket = '5 - 16') AS pop5_16_all,
        max(s.male_overall)      FILTER (WHERE s.vars = 'Population' AND s.age_bracket = '5 - 16') AS pop5_16_male,
        max(s.female_overall)    FILTER (WHERE s.vars = 'Population' AND s.age_bracket = '5 - 16') AS pop5_16_female
    FROM stg_t13b AS s
    JOIN dim_district AS d
      ON d.province_code = s.province_code AND d.census_name = s.name_admin_unit
    WHERE s.admin_unit = 'DISTRICT'
    GROUP BY d.district_id
), a AS (
    SELECT
        d.district_id,
        max(s.all_sexes_overall) FILTER (WHERE s.vars = 'Population' AND s.age_bracket = '5 - 16') AS xchk_pop5_16_all_t13a
    FROM stg_t13a AS s
    JOIN dim_district AS d
      ON d.province_code = s.province_code AND d.census_name = s.name_admin_unit
    WHERE s.admin_unit = 'DISTRICT'
    GROUP BY d.district_id
)
SELECT * FROM b LEFT JOIN a USING (district_id);

-- Table 16: disability.
CREATE OR REPLACE TABLE cnt_t16 AS
SELECT
    d.district_id,
    max(s.all_sexes_overall) FILTER (WHERE s.disab_func_lim = 'Population') AS pop_t16_all,
    max(s.all_sexes_overall) FILTER (WHERE s.disab_func_lim = 'Disability') AS disability_all
FROM stg_t16 AS s
JOIN dim_district AS d
  ON d.province_code = s.province_code AND d.census_name = s.name_admin_unit
WHERE s.admin_unit = 'DISTRICT'
GROUP BY d.district_id;

-- Table 20: households by type of structure.
CREATE OR REPLACE TABLE cnt_t20 AS
SELECT
    d.district_id,
    max(s.overall) FILTER (WHERE s.hh_type = 'TOTAL')      AS households_t20,
    max(s.overall) FILTER (WHERE s.hh_type = 'PAKKA')      AS hh_pakka,
    max(s.overall) FILTER (WHERE s.hh_type = 'SEMI PAKKA') AS hh_semi_pakka,
    max(s.overall) FILTER (WHERE s.hh_type = 'KACHA')      AS hh_kacha
FROM stg_t20 AS s
JOIN dim_district AS d
  ON d.province_code = s.province_code AND d.census_name = s.name_admin_unit
WHERE s.admin_unit = 'DISTRICT'
GROUP BY d.district_id;

-- Tables 22-25: household amenities and tenure (region = OVERALL rows only).
CREATE OR REPLACE TABLE cnt_t22_25 AS
WITH t22 AS (
    SELECT province_code, name_admin_unit, households,
           light_elect, light_solar, light_others,
           fuel_gas, fuel_lpgcng, fuel_firewood, fuel_others
    FROM stg_t22 WHERE admin_unit = 'DISTRICT' AND region = 'OVERALL'
), t23 AS (
    SELECT province_code, name_admin_unit, households AS households_t23,
           drink_wtr_improve, drink_wtr_inside
    FROM stg_t23 WHERE admin_unit = 'DISTRICT' AND region = 'OVERALL'
), t24 AS (
    SELECT province_code, name_admin_unit, households AS households_t24,
           toilet_flush, toilet_non_flush,
           -- Orakzai prints a blank here; flush + non-flush already equal all
           -- households, so the blank is a zero. Anything else stays NULL.
           CASE
               WHEN toilet_none IS NOT NULL THEN toilet_none
               WHEN toilet_flush + toilet_non_flush = households THEN 0
           END AS toilet_none
    FROM stg_t24 WHERE admin_unit = 'DISTRICT' AND region = 'OVERALL'
), t25 AS (
    SELECT province_code, name_admin_unit, households AS households_t25,
           res_st_owned, res_st_rented, res_st_rent_free,
           owner_gender_male, owner_gender_female, no_rooms_one
    FROM stg_t25 WHERE admin_unit = 'DISTRICT' AND region = 'OVERALL'
)
SELECT
    d.district_id,
    t22.households,
    t22.light_elect        AS hh_light_electric,
    t22.light_solar        AS hh_light_solar,
    t22.light_others       AS hh_light_other,
    t22.fuel_gas           AS hh_fuel_gas,
    t22.fuel_lpgcng        AS hh_fuel_lpg,
    t22.fuel_firewood      AS hh_fuel_firewood,
    t22.fuel_others        AS hh_fuel_other,
    t23.households_t23,
    t23.drink_wtr_improve  AS hh_water_improved,
    t23.drink_wtr_inside   AS hh_water_inside,
    t24.households_t24,
    t24.toilet_flush       AS hh_toilet_flush,
    t24.toilet_non_flush   AS hh_toilet_non_flush,
    t24.toilet_none        AS hh_toilet_none,
    t25.households_t25,
    t25.res_st_owned       AS hh_owned,
    t25.res_st_rented      AS hh_rented,
    t25.res_st_rent_free   AS hh_rent_free,
    t25.no_rooms_one       AS hh_one_room,
    t25.owner_gender_male   AS owner_male,
    t25.owner_gender_female AS owner_female,
    t25.owner_gender_male + t25.owner_gender_female AS owner_any
FROM dim_district AS d
LEFT JOIN t22 ON t22.province_code = d.province_code AND t22.name_admin_unit = d.census_name
LEFT JOIN t23 ON t23.province_code = d.province_code AND t23.name_admin_unit = d.census_name
LEFT JOIN t24 ON t24.province_code = d.province_code AND t24.name_admin_unit = d.census_name
LEFT JOIN t25 ON t25.province_code = d.province_code AND t25.name_admin_unit = d.census_name;

-- One wide row per district.
CREATE OR REPLACE TABLE district_counts AS
SELECT *
FROM dim_district
LEFT JOIN cnt_t01    USING (district_id)
LEFT JOIN cnt_t12    USING (district_id)
LEFT JOIN cnt_t13    USING (district_id)
LEFT JOIN cnt_t16    USING (district_id)
LEFT JOIN cnt_t20    USING (district_id)
LEFT JOIN cnt_t22_25 USING (district_id)
ORDER BY province_code, district_name;
