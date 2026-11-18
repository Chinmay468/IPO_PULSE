"""add ipo_applications table

Revision ID: 017_add_ipo_applications
Revises: 016_remove_portfolio_and_mutual_funds
Create Date: 2026-11-18 14:05:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '017_add_ipo_applications'
down_revision: Union[str, None] = '016_remove_portfolio_and_mutual_funds'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ipo_applications" not in inspector.get_table_names():
        op.create_table(
            "ipo_applications",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("ipo_id", sa.Integer(), sa.ForeignKey("ipos.id", ondelete="CASCADE"), nullable=False),
            sa.Column("applicant_name", sa.String(100), nullable=False, server_default="Self"),
            sa.Column("category", sa.String(50), nullable=False, server_default="RETAIL"),
            sa.Column("lots_applied", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("shares_applied", sa.Integer(), nullable=False),
            sa.Column("bid_price", sa.Float(), nullable=False),
            sa.Column("amount_blocked", sa.Float(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="APPLIED"),
            sa.Column("lots_allotted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("shares_allotted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("selling_price", sa.Float(), nullable=True),
            sa.Column("realized_profit", sa.Float(), nullable=True),
            sa.Column("notes", sa.String(255), nullable=True),
            sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_ipo_applications_user_id", "ipo_applications", ["user_id"])
        op.create_index("ix_ipo_applications_ipo_id", "ipo_applications", ["ipo_id"])
        op.create_index("ix_ipo_applications_status", "ipo_applications", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ipo_applications_status", table_name="ipo_applications", if_exists=True)
    op.drop_index("ix_ipo_applications_ipo_id", table_name="ipo_applications", if_exists=True)
    op.drop_index("ix_ipo_applications_user_id", table_name="ipo_applications", if_exists=True)
    op.drop_table("ipo_applications", if_exists=True)
