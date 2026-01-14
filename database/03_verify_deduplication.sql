-- ============================================================================
-- 03_verify_deduplication.sql
--
-- Purpose: Verify that deduplication was successful
--
-- This script checks:
-- 1. No remaining duplicates
-- 2. Expected row count reduction
-- 3. Sample data to confirm correct names were kept
-- 4. Test Austin query (the original problem case)
--
-- Usage:
--   psql -h localhost -U city_growth_postgres -d postgres -f 03_verify_deduplication.sql
-- ============================================================================

\echo '============================================================================'
\echo 'DEDUPLICATION VERIFICATION'
\echo '============================================================================'
\echo ''

-- Check 1: Verify no duplicates remain
\echo '1. CHECK: Are there any remaining duplicates?'
\echo '----------------------------------------------------------------'
WITH unique_names AS (
    SELECT DISTINCT area_fips, area_title
    FROM msa_wages_employment_data
),
duplicates AS (
    SELECT area_fips, COUNT(*) as variants
    FROM unique_names
    GROUP BY area_fips
    HAVING COUNT(*) > 1
)
SELECT
    CASE
        WHEN COUNT(*) = 0 THEN '✓ PASS: No duplicates found'
        ELSE '✗ FAIL: ' || COUNT(*)::TEXT || ' MSAs still have duplicates'
    END as result
FROM duplicates;

\echo ''
\echo '2. CHECK: Row count reduction'
\echo '----------------------------------------------------------------'
SELECT
    (SELECT COUNT(*) FROM msa_wages_employment_data_backup) as original_rows,
    (SELECT COUNT(*) FROM msa_wages_employment_data) as current_rows,
    (SELECT COUNT(*) FROM msa_wages_employment_data_backup) -
    (SELECT COUNT(*) FROM msa_wages_employment_data) as rows_removed,
    ROUND(100.0 *
        ((SELECT COUNT(*) FROM msa_wages_employment_data_backup) -
         (SELECT COUNT(*) FROM msa_wages_employment_data)) /
        (SELECT COUNT(*) FROM msa_wages_employment_data_backup)::numeric,
    2) as pct_removed;

\echo ''
\echo '3. CHECK: Unique area_fips per MSA'
\echo '----------------------------------------------------------------'
SELECT
    COUNT(DISTINCT area_fips) as unique_msas,
    COUNT(DISTINCT area_title) as unique_names,
    CASE
        WHEN COUNT(DISTINCT area_fips) = COUNT(DISTINCT area_title)
        THEN '✓ PASS: Each MSA has exactly one name'
        ELSE '✗ FAIL: Mismatch between MSAs and names'
    END as result
FROM msa_wages_employment_data;

\echo ''
\echo '4. SAMPLE: Austin query (original problem case)'
\echo '----------------------------------------------------------------'
SELECT area_fips, area_title, year, avg_annual_pay
FROM msa_wages_employment_data
WHERE area_title ILIKE '%Austin%' AND year = 2023 AND qtr = 'A'
ORDER BY area_fips;

\echo ''
\echo '5. SAMPLE: 10 MSAs that had duplicates - verify longest kept'
\echo '----------------------------------------------------------------'
WITH previously_affected AS (
    SELECT DISTINCT area_fips
    FROM msa_wages_employment_data_backup
    WHERE area_fips IN (
        SELECT area_fips
        FROM (
            SELECT DISTINCT area_fips, area_title
            FROM msa_wages_employment_data_backup
        ) sub
        GROUP BY area_fips
        HAVING COUNT(*) > 1
    )
    LIMIT 10
)
SELECT
    pa.area_fips,
    (SELECT DISTINCT area_title FROM msa_wages_employment_data m
     WHERE m.area_fips = pa.area_fips) as current_name,
    LENGTH((SELECT DISTINCT area_title FROM msa_wages_employment_data m
            WHERE m.area_fips = pa.area_fips)) as name_length,
    STRING_AGG(DISTINCT backup.area_title, ' vs ' ORDER BY backup.area_title) as original_variants
FROM previously_affected pa
JOIN msa_wages_employment_data_backup backup ON pa.area_fips = backup.area_fips
GROUP BY pa.area_fips
ORDER BY pa.area_fips;

\echo ''
\echo '6. CHECK: Data integrity (verify no data loss for kept names)'
\echo '----------------------------------------------------------------'
WITH current_data AS (
    SELECT area_fips, year, COUNT(*) as row_count
    FROM msa_wages_employment_data
    GROUP BY area_fips, year
),
backup_canonical AS (
    SELECT
        area_fips,
        year,
        COUNT(*) as row_count
    FROM (
        SELECT DISTINCT ON (m.area_fips, m.year, m.qtr, m.size_code)
            m.*
        FROM msa_wages_employment_data_backup m
        JOIN (
            SELECT DISTINCT ON (area_fips)
                area_fips,
                area_title as canonical_name
            FROM (
                SELECT DISTINCT area_fips, area_title
                FROM msa_wages_employment_data_backup
            ) sub
            ORDER BY area_fips, LENGTH(area_title) DESC, area_title
        ) names ON m.area_fips = names.area_fips AND m.area_title = names.canonical_name
    ) deduped
    GROUP BY area_fips, year
)
SELECT
    CASE
        WHEN COUNT(*) FILTER (WHERE c.row_count != b.row_count) = 0
        THEN '✓ PASS: All row counts match for kept names'
        ELSE '✗ FAIL: ' || COUNT(*) FILTER (WHERE c.row_count != b.row_count)::TEXT ||
             ' mismatches found'
    END as result
FROM current_data c
FULL OUTER JOIN backup_canonical b
    ON c.area_fips = b.area_fips AND c.year = b.year;

\echo ''
\echo '============================================================================'
\echo 'VERIFICATION COMPLETE'
\echo '============================================================================'
