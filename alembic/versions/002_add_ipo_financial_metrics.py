"""add ipo financial metrics

Revision ID: 002_add_ipo_financial_metrics
Revises: 001_initial_ipo_schema
Create Date: 2026-10-01 19:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_add_ipo_financial_metrics'
down_revision: Union[str, None] = '001_initial_ipo_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ipos') as batch_op:
        batch_op.add_column(sa.Column('sector', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('revenue_growth_yoy', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('pat_growth_yoy', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('debt_to_equity', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('pat_margin_pct', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('promoter_holding_pre', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('promoter_holding_post', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ipos') as batch_op:
        batch_op.drop_column('promoter_holding_post')
        batch_op.drop_column('promoter_holding_pre')
        batch_op.drop_column('pat_margin_pct')
        batch_op.drop_column('debt_to_equity')
        batch_op.drop_column('pat_growth_yoy')
        batch_op.drop_column('revenue_growth_yoy')
        batch_op.drop_column('sector')
