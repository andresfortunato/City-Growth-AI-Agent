# Database Scripts

SQL scripts for managing the QCEW MSA wages and employment database.

## Directory Structure

```
database/
├── README.md                        # This file
├── 01_analyze_duplicates.sql        # Analyze duplicate area_title values
├── 02_deduplicate_area_titles.sql   # Remove duplicate area_titles (DESTRUCTIVE)
└── 03_verify_deduplication.sql      # Verify deduplication was successful
```

---

## Problem: Duplicate Area Titles

The `msa_wages_employment_data` table has **68 MSAs** with duplicate rows - same `area_fips` (MSA identifier) but different `area_title` values.

**Example:**
```
area_fips: C1242
  → "Austin-Round Rock, TX"            (shorter, older name)
  → "Austin-Round Rock-San Marcos, TX" (longer, includes county)
```

This happens because the Bureau of Labor Statistics added counties to MSA names over time but kept both naming conventions in the dataset.

**Impact:**
- Queries like `WHERE area_title ILIKE '%Austin%'` return duplicate rows
- Confusing for users (which Austin is correct?)
- ~5,400 duplicate rows (about 50% of the dataset)

---

## Solution: Keep Longest Name

**Strategy:**
- For each `area_fips` with multiple `area_title` values
- **Keep** the longest `area_title` (assumes longer = more complete with county names)
- **Delete** all shorter variants
- If tied on length, keep alphabetically first

---

## Usage

### Step 1: Analyze (Safe - Read Only)

Run the analysis script to see what will be affected:

```bash
psql -h localhost -U city_growth_postgres -d postgres \
  -f database/01_analyze_duplicates.sql
```

**This script shows:**
- How many MSAs have duplicates (68 expected)
- Which area_title will be kept vs deleted for each MSA
- Total row count impact (~5,400 rows to delete)
- Sample of affected MSAs

### Step 2: Deduplicate (DESTRUCTIVE)

**⚠️ WARNING: This deletes data!**

The script creates a backup table first, but review the analysis output before proceeding.

```bash
psql -h localhost -U city_growth_postgres -d postgres \
  -f database/02_deduplicate_area_titles.sql
```

**This script:**
1. Creates `msa_wages_employment_data_backup` (full copy)
2. Deletes rows with shorter `area_title` values
3. Shows summary of deletion

**Safety:**
- Backup table created before any changes
- 3-second delay with Ctrl+C abort option
- Rollback instructions provided

### Step 3: Verify (Safe - Read Only)

Verify the deduplication worked correctly:

```bash
psql -h localhost -U city_growth_postgres -d postgres \
  -f database/03_verify_deduplication.sql
```

**This script checks:**
- ✓ No remaining duplicates
- ✓ Expected row count reduction
- ✓ Austin query returns 1 row (not 2)
- ✓ Sample MSAs show longest names kept
- ✓ Data integrity for kept names

---

## Rollback (If Needed)

If something goes wrong, restore from backup:

```sql
-- Connect to database
psql -h localhost -U city_growth_postgres -d postgres

-- Restore from backup
DROP TABLE msa_wages_employment_data;
ALTER TABLE msa_wages_employment_data_backup
  RENAME TO msa_wages_employment_data;
```

---

## Expected Results

**Before:**
```sql
SELECT * FROM msa_wages_employment_data
WHERE area_title ILIKE '%Austin%' AND year = 2023;
-- Returns 2 rows (duplicate)
```

**After:**
```sql
SELECT * FROM msa_wages_employment_data
WHERE area_title ILIKE '%Austin%' AND year = 2023;
-- Returns 1 row: "Austin-Round Rock-San Marcos, TX"
```

---

## Database Connection

Scripts use these connection parameters (from `.env`):

```bash
Host:     localhost
Port:     5432
User:     city_growth_postgres
Password: (see .env)
Database: postgres
```

To run with explicit credentials:

```bash
source .env
PGPASSWORD=$DB_PASSWORD \
psql -h localhost -U city_growth_postgres -d postgres \
  -f database/01_analyze_duplicates.sql
```

---

## Maintenance

After deduplication, you can optionally:

1. **Drop backup table** (once verified):
   ```sql
   DROP TABLE msa_wages_employment_data_backup;
   ```

2. **Add constraint** to prevent future duplicates:
   ```sql
   -- Create unique constraint on (area_fips, year, qtr, size_code)
   -- This prevents duplicate rows from being inserted
   ALTER TABLE msa_wages_employment_data
   ADD CONSTRAINT unique_msa_year_qtr_size
   UNIQUE (area_fips, year, qtr, size_code);
   ```

3. **Vacuum table** to reclaim space:
   ```sql
   VACUUM FULL msa_wages_employment_data;
   ```
