"""add suggestion_log table for swing stock tracking

Revision ID: 003_add_suggestion_log
Revises: 002_add_ipo_financial_metrics
Create Date: 2026-10-05 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_add_suggestion_log'
down_revision: Union[str, None] = '002_add_ipo_financial_metrics'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'suggestion_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('target', sa.Float(), nullable=False),
        sa.Column('stop', sa.Float(), nullable=False),
        sa.Column('atr', sa.Float(), nullable=True),
        sa.Column('reasons', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='open', nullable=False),
        sa.Column('exit_date', sa.Date(), nullable=True),
        sa.Column('exit_price', sa.Float(), nullable=True),
        sa.Column('return_pct', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('suggestion_log') as batch_op:
        batch_op.create_index('ix_suggestion_log_id', ['id'], unique=False)
        batch_op.create_index('ix_suggestion_log_date', ['date'], unique=False)
        batch_op.create_index('ix_suggestion_log_symbol', ['symbol'], unique=False)
        batch_op.create_index('ix_suggestion_log_status', ['status'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('suggestion_log') as batch_op:
        batch_op.drop_index('ix_suggestion_log_status')
        batch_op.drop_index('ix_suggestion_log_symbol')
        batch_op.drop_index('ix_suggestion_log_date')
        batch_op.drop_index('ix_suggestion_log_id')
    op.drop_table('suggestion_log')
