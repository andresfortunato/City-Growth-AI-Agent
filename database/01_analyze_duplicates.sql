-- ============================================================================
-- 01_analyze_duplicates.sql
--
-- Purpose: Analyze duplicate area_title values for same area_fips
--
-- This script identifies MSAs with multiple area_title variants and shows:
-- - How many MSAs are affected
-- - Which names will be kept (longest) vs deleted (shorter)
-- - Total row counts before deduplication
--
-- Usage:
--   psql -h localhost -U city_growth_postgres -d postgres -f 01_analyze_duplicates.sql
-- ============================================================================

\echo '============================================================================'
\echo 'DUPLICATE AREA_TITLE ANALYSIS'
\echo '============================================================================'
\echo ''

-- Summary: Count of affected MSAs
\echo '1. SUMMARY: MSAs with duplicate area_title values'
\echo '----------------------------------------------------------------'
WITH unique_names AS (
    SELECT DISTINCT area_fips, area_title
    FROM msa_wages_employment_data
)
SELECT
    COUNT(*) as affected_msas,
    (SELECT COUNT(DISTINCT area_fips) FROM msa_wages_employment_data) as total_msas,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(DISTINCT area_fips) FROM msa_wages_employment_data), 2) as pct_affected
FROM (
    SELECT area_fips
    FROM unique_names
    GROUP BY area_fips
    HAVING COUNT(*) > 1
) sub;

\echo ''
\echo '2. AFFECTED MSAs: Which area_fips have duplicates?'
\echo '----------------------------------------------------------------'
WITH unique_names AS (
    SELECT DISTINCT area_fips, area_title
    FROM msa_wages_employment_data
),
duplicates AS (
    SELECT
        area_fips,
        COUNT(*) as name_variants
    FROM unique_names
    GROUP BY area_fips
    HAVING COUNT(*) > 1
)
SELECT
    d.area_fips,
    d.name_variants,
    MAX(CASE WHEN rn = 1 THEN u.area_title END) as longest_name_to_keep,
    MAX(CASE WHEN rn = 2 THEN u.area_title END) as shorter_name_to_delete
FROM duplicates d
JOIN (
    SELECT
        area_fips,
        area_title,
        ROW_NUMBER() OVER (PARTITION BY area_fips ORDER BY LENGTH(area_title) DESC, area_title) as rn
    FROM unique_names
) u ON d.area_fips = u.area_fips
GROUP BY d.area_fips, d.name_variants
ORDER BY d.area_fips;

\echo ''
\echo '3. ROW IMPACT: How many rows will be deleted?'
\echo '----------------------------------------------------------------'
WITH names_to_keep AS (
    SELECT DISTINCT ON (area_fips)
        area_fips,
        area_title as canonical_name
    FROM (
        SELECT DISTINCT area_fips, area_title
        FROM msa_wages_employment_data
    ) sub
    ORDER BY area_fips, LENGTH(area_title) DESC, area_title
)
SELECT
    COUNT(*) as total_rows_current,
    COUNT(*) FILTER (WHERE ntk.canonical_name = m.area_title) as rows_to_keep,
    COUNT(*) FILTER (WHERE ntk.canonical_name != m.area_title) as rows_to_delete,
    ROUND(100.0 * COUNT(*) FILTER (WHERE ntk.canonical_name != m.area_title) / COUNT(*), 2) as pct_to_delete
FROM msa_wages_employment_data m
JOIN names_to_keep ntk ON m.area_fips = ntk.area_fips;

\echo ''
\echo '4. SAMPLE: First 10 affected MSAs with before/after'
\echo '----------------------------------------------------------------'
WITH unique_names AS (
    SELECT DISTINCT area_fips, area_title
    FROM msa_wages_employment_data
),
duplicates AS (
    SELECT area_fips
    FROM unique_names
    GROUP BY area_fips
    HAVING COUNT(*) > 1
    LIMIT 10
)
SELECT
    u.area_fips,
    u.area_title,
    LENGTH(u.area_title) as name_length,
    CASE
        WHEN u.area_title = (
            SELECT area_title
            FROM unique_names u2
            WHERE u2.area_fips = u.area_fips
            ORDER BY LENGTH(area_title) DESC, area_title
            LIMIT 1
        ) THEN 'KEEP'
        ELSE 'DELETE'
    END as action
FROM unique_names u
WHERE u.area_fips IN (SELECT area_fips FROM duplicates)
ORDER BY u.area_fips, LENGTH(u.area_title) DESC;

\echo ''
\echo '============================================================================'
\echo 'Analysis complete. Review the results before running deduplication.'
\echo '============================================================================'
