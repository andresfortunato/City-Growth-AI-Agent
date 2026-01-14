-- ============================================================================
-- 02_deduplicate_area_titles.sql
--
-- Purpose: Remove duplicate area_title rows, keeping the longest name per area_fips
--
-- Strategy:
-- 1. For each area_fips with multiple area_title values
-- 2. Keep the LONGEST area_title (assumption: longer = more complete with county names)
-- 3. If tied on length, keep alphabetically first
-- 4. Delete all other rows for that area_fips
--
-- IMPORTANT: This is a DESTRUCTIVE operation. Run 01_analyze_duplicates.sql first!
--
-- Usage:
--   psql -h localhost -U city_growth_postgres -d postgres -f 02_deduplicate_area_titles.sql
--
-- Rollback: This script creates a backup table first for safety
-- ============================================================================

\echo '============================================================================'
\echo 'AREA_TITLE DEDUPLICATION'
\echo '============================================================================'
\echo ''

-- Step 1: Create backup table
\echo '1. Creating backup table: msa_wages_employment_data_backup'
\echo '----------------------------------------------------------------'
DROP TABLE IF EXISTS msa_wages_employment_data_backup;
CREATE TABLE msa_wages_employment_data_backup AS
SELECT * FROM msa_wages_employment_data;

\echo 'Backup created successfully.'
\echo ''

-- Step 2: Show what will be deleted (for final confirmation)
\echo '2. Preview: Rows to be deleted'
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
    COUNT(*) as rows_to_delete
FROM msa_wages_employment_data m
JOIN names_to_keep ntk ON m.area_fips = ntk.area_fips
WHERE m.area_title != ntk.canonical_name;

\echo ''
\echo 'Proceeding with deletion in 3 seconds...'
\echo 'Press Ctrl+C to abort!'
SELECT pg_sleep(3);
\echo ''

-- Step 3: Delete shorter area_title variants
\echo '3. Deleting duplicate rows...'
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
DELETE FROM msa_wages_employment_data m
USING names_to_keep ntk
WHERE m.area_fips = ntk.area_fips
  AND m.area_title != ntk.canonical_name;

\echo 'Deletion complete.'
\echo ''

-- Step 4: Verify results
\echo '4. Verification: Checking for remaining duplicates'
\echo '----------------------------------------------------------------'
WITH unique_names AS (
    SELECT DISTINCT area_fips, area_title
    FROM msa_wages_employment_data
)
SELECT
    COUNT(*) as msas_with_duplicates
FROM (
    SELECT area_fips
    FROM unique_names
    GROUP BY area_fips
    HAVING COUNT(*) > 1
) sub;

\echo ''
\echo '5. Final row count comparison'
\echo '----------------------------------------------------------------'
SELECT
    (SELECT COUNT(*) FROM msa_wages_employment_data_backup) as rows_before,
    (SELECT COUNT(*) FROM msa_wages_employment_data) as rows_after,
    (SELECT COUNT(*) FROM msa_wages_employment_data_backup) -
    (SELECT COUNT(*) FROM msa_wages_employment_data) as rows_deleted;

\echo ''
\echo '============================================================================'
\echo 'DEDUPLICATION COMPLETE'
\echo ''
\echo 'Backup table: msa_wages_employment_data_backup'
\echo 'To rollback: DROP TABLE msa_wages_employment_data;'
\echo '             ALTER TABLE msa_wages_employment_data_backup'
\echo '                  RENAME TO msa_wages_employment_data;'
\echo '============================================================================'
