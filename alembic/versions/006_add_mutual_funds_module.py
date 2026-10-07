"""add mutual funds module

Revision ID: 006_add_mutual_funds_module
Revises: 005_add_portfolio_snapshots
Create Date: 2026-10-07 11:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006_add_mutual_funds_module'
down_revision: Union[str, None] = '005_add_portfolio_snapshots'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. mf_schemes
    op.create_table(
        'mf_schemes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('scheme_code', sa.String(50), nullable=True),
        sa.Column('isin', sa.String(50), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('amc', sa.String(255), nullable=True),
        sa.Column('category', sa.String(100), nullable=True),
        sa.Column('plan_type', sa.String(50), nullable=True),
        sa.Column('option_type', sa.String(50), nullable=True),
        sa.Column('latest_nav', sa.Float(), nullable=True),
        sa.Column('latest_nav_date', sa.Date(), nullable=True),
        sa.Column('is_nav_stale', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('mf_schemes') as batch_op:
        batch_op.create_index('ix_mf_schemes_id', ['id'], unique=False)
        batch_op.create_index('ix_mf_schemes_scheme_code', ['scheme_code'], unique=False)
        batch_op.create_index('ix_mf_schemes_isin', ['isin'], unique=False)

    # 2. mf_holdings
    op.create_table(
        'mf_holdings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('scheme_id', sa.Integer(), nullable=False),
        sa.Column('folio_masked', sa.String(100), nullable=True),
        sa.Column('folio_hash', sa.String(64), nullable=True),
        sa.Column('units', sa.Float(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['scheme_id'], ['mf_schemes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('mf_holdings') as batch_op:
        batch_op.create_index('ix_mf_holdings_id', ['id'], unique=False)
        batch_op.create_index('ix_mf_holdings_scheme_id', ['scheme_id'], unique=False)
        batch_op.create_index('ix_mf_holdings_folio_hash', ['folio_hash'], unique=False)

    # 3. mf_transactions
    op.create_table(
        'mf_transactions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('holding_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('type', sa.Enum('BUY', 'SELL', 'SIP', 'SWITCH', 'DIVIDEND', name='mftransactiontype'), nullable=False),
        sa.Column('units', sa.Float(), nullable=False),
        sa.Column('nav', sa.Float(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['holding_id'], ['mf_holdings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('mf_transactions') as batch_op:
        batch_op.create_index('ix_mf_transactions_id', ['id'], unique=False)
        batch_op.create_index('ix_mf_transactions_holding_id', ['holding_id'], unique=False)
        batch_op.create_index('ix_mf_transactions_date', ['date'], unique=False)

    # 4. mf_nav_history
    op.create_table(
        'mf_nav_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('scheme_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('nav', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['scheme_id'], ['mf_schemes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('scheme_id', 'date', name='uq_mf_nav_scheme_date')
    )
    with op.batch_alter_table('mf_nav_history') as batch_op:
        batch_op.create_index('ix_mf_nav_history_id', ['id'], unique=False)
        batch_op.create_index('ix_mf_nav_history_scheme_id', ['scheme_id'], unique=False)
        batch_op.create_index('ix_mf_nav_history_date', ['date'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('mf_nav_history') as batch_op:
        batch_op.drop_index('ix_mf_nav_history_date')
        batch_op.drop_index('ix_mf_nav_history_scheme_id')
        batch_op.drop_index('ix_mf_nav_history_id')
    op.drop_table('mf_nav_history')

    with op.batch_alter_table('mf_transactions') as batch_op:
        batch_op.drop_index('ix_mf_transactions_date')
        batch_op.drop_index('ix_mf_transactions_holding_id')
        batch_op.drop_index('ix_mf_transactions_id')
    op.drop_table('mf_transactions')

    with op.batch_alter_table('mf_holdings') as batch_op:
        batch_op.drop_index('ix_mf_holdings_folio_hash')
        batch_op.drop_index('ix_mf_holdings_scheme_id')
        batch_op.drop_index('ix_mf_holdings_id')
    op.drop_table('mf_holdings')

    with op.batch_alter_table('mf_schemes') as batch_op:
        batch_op.drop_index('ix_mf_schemes_isin')
        batch_op.drop_index('ix_mf_schemes_scheme_code')
        batch_op.drop_index('ix_mf_schemes_id')
    op.drop_table('mf_schemes')
