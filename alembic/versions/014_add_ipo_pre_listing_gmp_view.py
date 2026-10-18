"""add ipo_pre_listing_gmp view

Revision ID: 014_add_ipo_pre_listing_gmp_view
Revises: 013_add_ipo_aliases
Create Date: 2026-10-16 15:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '014_add_ipo_pre_listing_gmp_view'
down_revision: Union[str, None] = '013_add_ipo_aliases'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"

    view_sql = """
    WITH ranked_gmp AS (
        SELECT 
            g.id AS gmp_id,
            g.ipo_id,
            g.gmp_amount,
            g.gmp_percentage,
            g.source,
            g.recorded_at,
            i.symbol,
            i.company_name,
            i.listing_date,
            i.issue_price,
            ROW_NUMBER() OVER (
                PARTITION BY g.ipo_id 
                ORDER BY g.recorded_at DESC
            ) AS rn
        FROM ipo_gmp g
        JOIN ipos i ON g.ipo_id = i.id
        WHERE (
            i.listing_date IS NULL 
            OR DATE(g.recorded_at) <= DATE(i.listing_date)
        )
    )
    SELECT 
        gmp_id,
        ipo_id,
        symbol,
        company_name,
        gmp_amount,
        gmp_percentage,
        source,
        recorded_at,
        listing_date,
        issue_price
    FROM ranked_gmp
    WHERE rn = 1
    """

    if is_postgres:
        op.execute(f"CREATE OR REPLACE VIEW ipo_pre_listing_gmp AS {view_sql};")
    else:
        op.execute("DROP VIEW IF EXISTS ipo_pre_listing_gmp;")
        op.execute(f"CREATE VIEW ipo_pre_listing_gmp AS {view_sql};")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS ipo_pre_listing_gmp;")
