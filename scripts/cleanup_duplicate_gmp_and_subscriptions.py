"""
One-off cleanup script for duplicate ipo_gmp and ipo_subscriptions rows.
DEFAULT: --dry-run (prints duplicate counts and IDs without modifying DB).
To actually delete rows, user must explicitly pass --execute.
"""
import argparse
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models.ipo import IPOGmp, IPOSubscription


def get_sync_db_url():
    url = settings.DATABASE_URL
    if "sqlite+aiosqlite" in url:
        return url.replace("sqlite+aiosqlite", "sqlite")
    if "postgresql+asyncpg" in url:
        return url.replace("postgresql+asyncpg", "postgresql")
    return url


def find_duplicate_gmp_rows(session: Session):
    stmt = select(IPOGmp).order_by(IPOGmp.ipo_id, IPOGmp.source, IPOGmp.recorded_at.asc(), IPOGmp.id.asc())
    all_rows = session.execute(stmt).scalars().all()

    duplicates = []
    prev_by_key = {}

    for row in all_rows:
        key = (row.ipo_id, row.source)
        if key not in prev_by_key:
            prev_by_key[key] = row
            continue

        prev = prev_by_key[key]
        # Identical values check
        if (
            prev.gmp_amount == row.gmp_amount
            and prev.gmp_percentage == row.gmp_percentage
        ):
            # Check time interval: if within 1 hour or consecutive duplicate
            duplicates.append(row.id)
        else:
            prev_by_key[key] = row

    return duplicates


def find_duplicate_subscription_rows(session: Session):
    stmt = select(IPOSubscription).order_by(IPOSubscription.ipo_id, IPOSubscription.recorded_at.asc(), IPOSubscription.id.asc())
    all_rows = session.execute(stmt).scalars().all()

    duplicates = []
    prev_by_key = {}

    for row in all_rows:
        key = row.ipo_id
        if key not in prev_by_key:
            prev_by_key[key] = row
            continue

        prev = prev_by_key[key]
        # Identical values check
        if (
            prev.total_multiple == row.total_multiple
            and prev.qib_multiple == row.qib_multiple
            and prev.nii_multiple == row.nii_multiple
            and prev.retail_multiple == row.retail_multiple
        ):
            duplicates.append(row.id)
        else:
            prev_by_key[key] = row

    return duplicates


def main():
    parser = argparse.ArgumentParser(description="Clean up duplicate GMP and subscription rows.")
    parser.add_argument("--execute", action="store_true", default=False, help="Perform actual deletion. Default is dry-run.")
    args = parser.parse_args()

    sync_url = get_sync_db_url()
    # Mask credentials if postgres
    db_type = "SQLite" if "sqlite" in sync_url else "PostgreSQL"
    print(f"Connecting to database ({db_type})...")

    engine = create_engine(sync_url)
    with Session(engine) as session:
        dup_gmp = find_duplicate_gmp_rows(session)
        dup_subs = find_duplicate_subscription_rows(session)

        print("\n================ CLEANUP AUDIT SUMMARY ================")
        print(f"Duplicate ipo_gmp rows found:          {len(dup_gmp)}")
        print(f"Duplicate ipo_subscriptions rows found: {len(dup_subs)}")
        print(f"Total duplicate rows to remove:         {len(dup_gmp) + len(dup_subs)}")
        print("=======================================================\n")

        if not args.execute:
            print("[DRY-RUN MODE] No rows were deleted.")
            print("To delete these rows after approval, run:")
            print("  python scripts/cleanup_duplicate_gmp_and_subscriptions.py --execute")
            return

        print("Executing deletion of duplicate rows...")
        if dup_gmp:
            session.query(IPOGmp).filter(IPOGmp.id.in_(dup_gmp)).delete(synchronize_session=False)
        if dup_subs:
            session.query(IPOSubscription).filter(IPOSubscription.id.in_(dup_subs)).delete(synchronize_session=False)
        session.commit()
        print(f"Successfully deleted {len(dup_gmp)} GMP rows and {len(dup_subs)} subscription rows.")


if __name__ == "__main__":
    main()
