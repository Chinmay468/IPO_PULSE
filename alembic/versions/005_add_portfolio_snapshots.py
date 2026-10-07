"""add portfolio snapshots table

Revision ID: 005_add_portfolio_snapshots
Revises: 004_add_prediction_tables
Create Date: 2026-10-06 14:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_add_portfolio_snapshots'
down_revision: Union[str, None] = '004_add_prediction_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'portfolio_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('invested', sa.Float(), nullable=False),
        sa.Column('current_value', sa.Float(), nullable=False),
        sa.Column('pnl', sa.Float(), nullable=False),
        sa.Column('priced_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date', name='uq_portfolio_snapshot_date')
    )
    with op.batch_alter_table('portfolio_snapshots') as batch_op:
        batch_op.create_index('ix_portfolio_snapshots_id', ['id'], unique=False)
        batch_op.create_index('ix_portfolio_snapshots_date', ['date'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('portfolio_snapshots') as batch_op:
        batch_op.drop_index('ix_portfolio_snapshots_date')
        batch_op.drop_index('ix_portfolio_snapshots_id')
    op.drop_table('portfolio_snapshots')
