"""remove portfolio and mutual funds

Revision ID: 016_remove_portfolio_and_mutual_funds
Revises: 015_add_price_history_and_data_coverage
Create Date: 2026-11-14 19:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '016_remove_portfolio_and_mutual_funds'
down_revision: Union[str, None] = '015_add_price_history_and_data_coverage'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"

    # 1. Drop data_coverage view if exists
    if is_postgres:
        op.execute("DROP VIEW IF EXISTS data_coverage CASCADE")
    else:
        op.execute("DROP VIEW IF EXISTS data_coverage")

    # 2. Drop tables in foreign-key dependency order with CASCADE
    tables_to_drop = [
        "data_issues",
        "price_history",
        "technical_diagnoses",
        "portfolio_snapshots",
        "suggestion_log",
        "prediction_results",
        "predictions",
        "mf_transactions",
        "mf_nav_history",
        "mf_holdings",
        "mf_schemes",
        "portfolio_transactions",
        "portfolio_holdings",
    ]

    for tbl in tables_to_drop:
        if is_postgres:
            op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
        else:
            op.execute(f"DROP TABLE IF EXISTS {tbl}")

    # 3. Drop PostgreSQL enum types if dialect is postgresql
    if is_postgres:
        enums_to_drop = [
            "directiontype",
            "direction_type",
            "mftransactiontype",
            "mf_transaction_type",
            "amccategory",
            "amc_category",
            "transactiontype",
            "transaction_type",
            "exchange"
        ]
        for enum_name in enums_to_drop:
            op.execute(f"DROP TYPE IF EXISTS {enum_name} CASCADE")


def downgrade() -> None:
    """
    Irreversible migration: complete removal of portfolio, mutual fund,
    price prediction, and technical analysis tables and data structures.
    """
    raise NotImplementedError(
        "Downgrade not supported: Portfolio, Mutual Fund, Prediction and Technical Analysis "
        "functionality has been permanently removed in favor of IPO-only scope."
    )
