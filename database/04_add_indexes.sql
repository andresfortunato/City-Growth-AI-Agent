-- ============================================================================
-- 04_add_indexes.sql
--
-- Purpose: Add performance indexes for common query patterns
--
-- Must run as postgres superuser (table owner):
--   sudo -u postgres psql -d postgres -f database/04_add_indexes.sql
-- ============================================================================

-- Enable trigram extension for ILIKE '%text%' performance
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Composite index for the most common filter pattern: WHERE year = X AND qtr = 'A'
CREATE INDEX IF NOT EXISTS idx_year_qtr ON msa_wages_employment_data(year, qtr);

-- Replace btree index on area_title with GIN trigram (supports ILIKE wildcard search)
-- Btree only helps with prefix matching (LIKE 'Austin%'), not middle matching (ILIKE '%Austin%')
DROP INDEX IF EXISTS idx_area_title;
CREATE INDEX idx_area_title_trgm ON msa_wages_employment_data USING GIN(area_title gin_trgm_ops);

\echo 'Indexes created successfully.'
\echo 'Verify with: SELECT indexname, indexdef FROM pg_indexes WHERE tablename = ''msa_wages_employment_data'';'
