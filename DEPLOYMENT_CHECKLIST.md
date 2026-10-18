# Production Deployment Checklist

This document outlines the strict, ordered pre-deployment, migration, validation, and rollback procedures for deploying the Multi-Source Consensus GMP, Dynamic Matching, and Scored Status features to production.

---

## 1. Safety & Compliance Rules
- **Confidentiality**: Never log, print, or commit `.env` or credential files.
- **External Feeds**: Ensure rate limits (2–3s delays), `robots.txt` compliance, caching, and User-Agent headers are enforced.
- **Data Preservation**: Do not drop tables or delete production IPO records.

---

## 2. Step 1: Pre-Deployment Database Backup (pg_dump)
Always take a full compressed binary backup before applying migrations or running maintenance jobs:

```bash
# Set timestamp variable
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Execute pg_dump with blob and verbose logging
pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -F c -b -v -f "enquirer_backup_${TIMESTAMP}.dump"

# Verify dump file was generated and non-empty
ls -lh "enquirer_backup_${TIMESTAMP}.dump"
```

---

## 3. Step 2: Ordered Alembic Migrations
Run Alembic migrations sequentially to update the database schema:

```bash
# Check current migration revision
alembic current

# Apply pending migrations up to head
alembic upgrade head
```

### Applied Migrations:
1. `013_add_ipo_aliases`: Adds the `ipo_aliases` table (`ipo_id`, `alias`, `source`, `created_at`) with btree indexes on `alias` and `ipo_id`.
2. `014_add_ipo_pre_listing_gmp_view`: Creates the `ipo_pre_listing_gmp` SQL view to preserve pre-listing GMP records for post-mortem listing gain tracking.

---

## 4. Step 3: Seed Data Flagging & Isolation
Ensure demo/benchmark rows (`Hyundai Motor India`, `NTPC Green Energy`) are marked `is_seed = true` to hide them from active counts, recommendations, and card grids:

```sql
UPDATE ipos 
SET is_seed = TRUE 
WHERE symbol IN ('HYUNDAI', 'NTPCGREEN') 
   OR company_name ILIKE '%Hyundai Motor%' 
   OR company_name ILIKE '%NTPC Green%';
```

---

## 5. Step 4: Stored Status Correction Job
Execute the status correction routine to synchronize stored `ipos.status` with derived IST calendar dates:

```bash
# Run standalone status sync and validation
python scripts/sync_postgres_replica.py --db-url "$DATABASE_URL"
```

This verifies:
- `Tonbo Imaging India`, `Fusion CX`, `Zetwerk`, `Sahajanand Medical`, `Ravita Engineering`, `Shellz India`, and `Bonfiglioli Transmissions` are stored as `LIVE`.
- `HD Fire Protect` and `Vaibhav Vyapaar` are stored as `CLOSED`.
- `Jio Platforms` and `Paras Healthcare` are stored as `UPCOMING`.
- `dates_tba` is forced to `false` whenever open and close dates are present.

---

## 6. Step 5: Scraper Dry Run & Health Checks
Trigger an on-demand market data sync and inspect API health:

```bash
# 1. Trigger background market data sync
curl -X POST "https://<your-domain>/api/v1/scraper/sync" \
     -H "Authorization: Bearer <ADMIN_TOKEN>"

# 2. Check operational scraper status and freshness
curl -X GET "https://<your-domain>/api/v1/scraper/status"
```

### Acceptance Criteria:
- `scheduler_running`: `true`.
- `is_discovery_stale`: `false` (last full sync < 24h).
- `gmp_quality.alert_active`: `false` (both InvestorGain & IPOWatch responsive; >50% live IPOs fresh).
- Consensus median calculated across sources with disagreement flags when sources diverge by >30%.

---

## 7. Step 6: Rollback Procedure (Emergency Only)
If an unrecoverable failure occurs during rollout:

### A. Revert Migrations via Alembic
```bash
# Downgrade schema back to pre-GMP state (Revision 012)
alembic downgrade 012_add_registrar_allotment_url
```

### B. Full Database Restoration from pg_dump
```bash
# Restore entire database from the pre-deployment dump
pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" --clean --if-exists -v "enquirer_backup_${TIMESTAMP}.dump"
```

---

## 8. Card Display States Reference

| Card Type | Status Pill | Recommendation Badge | Score Section | GMP Badge / State |
| :--- | :--- | :--- | :--- | :--- |
| **Live IPO** | `LIVE` (Green) | `APPLY` or `STRONG APPLY` | `XX.X / 100` numeric | `+₹XX (XX%)` with `N sources` |
| **Closed IPO** | `CLOSED` (Slate) | `Closed` (Slate pill) | `Score at close: XX.X` | Final Subscription (e.g. `131.7x`), Apply button suppressed |
| **Low Confidence** | `UPCOMING` (Blue) | `Insufficient data` | Hidden (`—`) | Missing inputs list displayed (`Missing: GMP, P/E...`) |
| **Extreme GMP** | `LIVE` (Green) | `Apply, verify GMP` (Amber) | Capped at Strong Band (max 28.0) | `Verify before relying` warning badge (>50% of issue price) |
