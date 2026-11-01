"""add price_history, data_issues and data_coverage view

Revision ID: 015_add_price_history_and_data_coverage
Revises: 014_add_ipo_pre_listing_gmp_view
Create Date: 2026-10-28 16:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '015_add_price_history_and_data_coverage'
down_revision: Union[str, None] = '014_add_ipo_pre_listing_gmp_view'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"

    # 1. Create price_history table
    op.create_table(
        'price_history',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('exchange', sa.String(length=10), server_default='NSE', nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('open', sa.Float(), nullable=False),
        sa.Column('high', sa.Float(), nullable=False),
        sa.Column('low', sa.Float(), nullable=False),
        sa.Column('close', sa.Float(), nullable=False),
        sa.Column('adj_close', sa.Float(), nullable=True),
        sa.Column('volume', sa.BigInteger(), nullable=True),
        sa.Column('source', sa.String(length=50), server_default='yfinance', nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'exchange', 'date', name='uq_price_history_symbol_exchange_date')
    )
    op.create_index('ix_price_history_symbol_date', 'price_history', ['symbol', 'date'])
    op.create_index('ix_price_history_symbol', 'price_history', ['symbol'])
    op.create_index('ix_price_history_date', 'price_history', ['date'])

    # 2. Create data_issues table
    op.create_table(
        'data_issues',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('exchange', sa.String(length=10), server_default='NSE', nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('issue_type', sa.String(length=50), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('severity', sa.String(length=20), server_default='WARNING', nullable=False),
        sa.Column('resolved', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_data_issues_symbol', 'data_issues', ['symbol'])
    op.create_index('ix_data_issues_date', 'data_issues', ['date'])
    op.create_index('ix_data_issues_issue_type', 'data_issues', ['issue_type'])

    # 3. Create data_coverage view
    view_sql = """
    SELECT 
        symbol,
        MIN(date) AS first_date,
        MAX(date) AS last_date,
        COUNT(*) AS row_count,
        0 AS missing_trading_days
    FROM price_history
    GROUP BY symbol
    """

    if is_postgres:
        op.execute(f"CREATE OR REPLACE VIEW data_coverage AS {view_sql};")
    else:
        op.execute("DROP VIEW IF EXISTS data_coverage;")
        op.execute(f"CREATE VIEW data_coverage AS {view_sql};")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS data_coverage;")
    op.drop_table('data_issues')
    op.drop_table('price_history')
