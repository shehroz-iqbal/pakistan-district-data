-- indicators: every catalogue indicator for every district, province and Pakistan,
-- computed by one query with GROUPING SETS so the three levels can never drift apart.
--
-- Rates are rebuilt from summed numerators and denominators. A district only
-- contributes to an aggregate when both its numerator and denominator exist, and
-- n_districts records how many did.

-- Long form of the count columns: (district, measure, amount).
CREATE OR REPLACE TABLE counts_long AS
UNPIVOT (
    SELECT district_id, COLUMNS(c -> c NOT IN ('district_id', 'district_name', 'census_name',
                                              'province_code', 'province_name',
                                              'map_unit_id', 'map_unit_name')
                                     AND c NOT LIKE 'pbs_%' AND c NOT LIKE 'xchk_%')
    FROM district_counts
)
ON COLUMNS(* EXCLUDE (district_id))
INTO NAME measure VALUE amount;

CREATE OR REPLACE TABLE indicator_values AS
WITH inputs AS (
    -- For each indicator and district: its numerator and denominator
    -- (or the single column, for counts).
    SELECT
        c.indicator_id,
        c.kind,
        c.multiplier,
        c.years,
        d.district_id,
        d.province_code,
        -- Only multi-district map units (Karachi) get their own aggregate row.
        CASE WHEN count(*) OVER (PARTITION BY c.indicator_id, d.map_unit_id) > 1
             THEN d.map_unit_id END AS map_unit_id,
        num.amount AS numerator,
        den.amount AS denominator
    FROM indicator_catalog AS c
    CROSS JOIN dim_district AS d
    LEFT JOIN counts_long AS num
      ON num.district_id = d.district_id AND num.measure = c.numerator_col
    LEFT JOIN counts_long AS den
      ON den.district_id = d.district_id AND den.measure = c.denominator_col
    WHERE c.kind IN ('count', 'ratio', 'growth')
),
aggregated AS (
    SELECT
        indicator_id,
        any_value(kind)       AS kind,
        any_value(multiplier) AS multiplier,
        any_value(years)      AS years,
        CASE
            WHEN GROUPING(district_id) = 0 THEN 'district'
            WHEN GROUPING(map_unit_id) = 0 THEN 'map_unit'
            WHEN GROUPING(province_code) = 0 THEN 'province'
            ELSE 'national'
        END AS level,
        CASE
            WHEN GROUPING(district_id) = 0 THEN district_id
            WHEN GROUPING(map_unit_id) = 0 THEN map_unit_id
            WHEN GROUPING(province_code) = 0 THEN province_code
            ELSE 'PK'
        END AS geo_id,
        sum(numerator)   FILTER (WHERE numerator IS NOT NULL
                                   AND (kind = 'count' OR denominator IS NOT NULL)) AS numerator,
        sum(denominator) FILTER (WHERE numerator IS NOT NULL
                                   AND denominator IS NOT NULL)                     AS denominator,
        count(*)         FILTER (WHERE numerator IS NOT NULL
                                   AND (kind = 'count' OR denominator IS NOT NULL)) AS n_districts
    FROM inputs
    GROUP BY GROUPING SETS (
        (indicator_id, province_code, district_id),
        (indicator_id, map_unit_id),
        (indicator_id, province_code),
        (indicator_id)
    )
    -- The map-unit grouping also yields one row for "no map unit"; drop it.
    HAVING NOT (GROUPING(map_unit_id) = 0 AND map_unit_id IS NULL)
),
computed AS (
    SELECT
        indicator_id, level, geo_id, numerator, denominator, n_districts,
        CASE kind
            WHEN 'count'  THEN numerator
            WHEN 'ratio'  THEN multiplier * numerator / nullif(denominator, 0)
            WHEN 'growth' THEN 100 * (power(numerator / nullif(denominator, 0), 1.0 / years) - 1)
        END AS value
    FROM aggregated
),
differences AS (
    -- e.g. literacy gender gap = male rate - female rate, at every level.
    SELECT
        c.indicator_id, a.level, a.geo_id,
        NULL::DOUBLE AS numerator, NULL::DOUBLE AS denominator,
        least(a.n_districts, b.n_districts) AS n_districts,
        a.value - b.value AS value
    FROM indicator_catalog AS c
    JOIN computed AS a ON a.indicator_id = c.minuend
    JOIN computed AS b ON b.indicator_id = c.subtrahend
                      AND b.level = a.level AND b.geo_id = a.geo_id
    WHERE c.kind = 'difference'
)
SELECT * FROM computed
UNION ALL
SELECT * FROM differences;

-- Wide table for spreadsheets: one row per district, one column per indicator
-- (the export step puts the columns in catalogue order).
CREATE OR REPLACE TABLE district_indicators AS
WITH p AS (
    PIVOT (SELECT geo_id AS district_id, indicator_id, value
           FROM indicator_values WHERE level = 'district')
    ON indicator_id
    USING first(value)
)
SELECT d.district_id, d.district_name, d.province_code, d.province_name,
       p.* EXCLUDE (district_id)
FROM dim_district AS d
JOIN p USING (district_id)
ORDER BY d.province_code, d.district_name;
