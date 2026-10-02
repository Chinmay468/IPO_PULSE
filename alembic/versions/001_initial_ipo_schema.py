"""initial ipo schema

Revision ID: 001_initial_ipo_schema
Revises: 
Create Date: 2026-09-30 16:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial_ipo_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create ipos table
    op.create_table(
        'ipos',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('company_name', sa.String(length=255), nullable=False),
        sa.Column('ipo_type', sa.Enum('MAINBOARD', 'SME', name='ipotype'), nullable=False),
        sa.Column('status', sa.Enum('UPCOMING', 'LIVE', 'CLOSED', 'LISTED', name='ipostatus'), nullable=False),
        sa.Column('price_band_low', sa.Float(), nullable=True),
        sa.Column('price_band_high', sa.Float(), nullable=True),
        sa.Column('issue_price', sa.Float(), nullable=True),
        sa.Column('lot_size', sa.Integer(), nullable=True),
        sa.Column('issue_size_crores', sa.Float(), nullable=True),
        sa.Column('fresh_issue_crores', sa.Float(), nullable=True),
        sa.Column('ofs_crores', sa.Float(), nullable=True),
        sa.Column('open_date', sa.Date(), nullable=True),
        sa.Column('close_date', sa.Date(), nullable=True),
        sa.Column('allotment_date', sa.Date(), nullable=True),
        sa.Column('refunds_initiation_date', sa.Date(), nullable=True),
        sa.Column('demat_credit_date', sa.Date(), nullable=True),
        sa.Column('listing_date', sa.Date(), nullable=True),
        sa.Column('registrar_name', sa.String(length=100), nullable=True),
        sa.Column('registrar_code', sa.String(length=100), nullable=True),
        sa.Column('pe_ratio', sa.Float(), nullable=True),
        sa.Column('industry_pe', sa.Float(), nullable=True),
        sa.Column('ronw', sa.Float(), nullable=True),
        sa.Column('eps', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ipos_id'), 'ipos', ['id'], unique=False)
    op.create_index(op.f('ix_ipos_symbol'), 'ipos', ['symbol'], unique=True)
    op.create_index(op.f('ix_ipos_company_name'), 'ipos', ['company_name'], unique=False)
    op.create_index(op.f('ix_ipos_status'), 'ipos', ['status'], unique=False)
    op.create_index(op.f('ix_ipos_open_date'), 'ipos', ['open_date'], unique=False)
    op.create_index(op.f('ix_ipos_close_date'), 'ipos', ['close_date'], unique=False)

    # 2. Create ipo_subscriptions table
    op.create_table(
        'ipo_subscriptions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ipo_id', sa.Integer(), nullable=False),
        sa.Column('qib_multiple', sa.Float(), nullable=True),
        sa.Column('nii_multiple', sa.Float(), nullable=True),
        sa.Column('retail_multiple', sa.Float(), nullable=True),
        sa.Column('employee_multiple', sa.Float(), nullable=True),
        sa.Column('total_multiple', sa.Float(), nullable=False),
        sa.Column('qib_shares_offered', sa.Float(), nullable=True),
        sa.Column('qib_shares_bid', sa.Float(), nullable=True),
        sa.Column('nii_shares_offered', sa.Float(), nullable=True),
        sa.Column('nii_shares_bid', sa.Float(), nullable=True),
        sa.Column('retail_shares_offered', sa.Float(), nullable=True),
        sa.Column('retail_shares_bid', sa.Float(), nullable=True),
        sa.Column('total_shares_offered', sa.Float(), nullable=True),
        sa.Column('total_shares_bid', sa.Float(), nullable=True),
        sa.Column('day_number', sa.Integer(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['ipo_id'], ['ipos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ipo_subscriptions_id'), 'ipo_subscriptions', ['id'], unique=False)
    op.create_index(op.f('ix_ipo_subscriptions_ipo_id'), 'ipo_subscriptions', ['ipo_id'], unique=False)
    op.create_index(op.f('ix_ipo_subscriptions_recorded_at'), 'ipo_subscriptions', ['recorded_at'], unique=False)

    # 3. Create ipo_gmp table
    op.create_table(
        'ipo_gmp',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ipo_id', sa.Integer(), nullable=False),
        sa.Column('gmp_amount', sa.Float(), nullable=False),
        sa.Column('gmp_percentage', sa.Float(), nullable=False),
        sa.Column('estimated_listing_price', sa.Float(), nullable=True),
        sa.Column('kostak_rate', sa.Float(), nullable=True),
        sa.Column('subject_to_sauda', sa.Float(), nullable=True),
        sa.Column('source', sa.String(length=100), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['ipo_id'], ['ipos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ipo_gmp_id'), 'ipo_gmp', ['id'], unique=False)
    op.create_index(op.f('ix_ipo_gmp_ipo_id'), 'ipo_gmp', ['ipo_id'], unique=False)
    op.create_index(op.f('ix_ipo_gmp_recorded_at'), 'ipo_gmp', ['recorded_at'], unique=False)

    # 4. Create ipo_scores table
    op.create_table(
        'ipo_scores',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ipo_id', sa.Integer(), nullable=False),
        sa.Column('composite_score', sa.Float(), nullable=False),
        sa.Column('recommendation', sa.Enum('STRONG APPLY', 'APPLY', 'NEUTRAL', 'AVOID', name='recommendationtype'), nullable=False),
        sa.Column('gmp_score', sa.Float(), nullable=False),
        sa.Column('subscription_score', sa.Float(), nullable=False),
        sa.Column('valuation_score', sa.Float(), nullable=False),
        sa.Column('structure_score', sa.Float(), nullable=False),
        sa.Column('rationale', sa.JSON(), nullable=True),
        sa.Column('calculated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['ipo_id'], ['ipos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ipo_scores_id'), 'ipo_scores', ['id'], unique=False)
    op.create_index(op.f('ix_ipo_scores_ipo_id'), 'ipo_scores', ['ipo_id'], unique=True)


def downgrade() -> None:
    op.drop_table('ipo_scores')
    op.drop_table('ipo_gmp')
    op.drop_table('ipo_subscriptions')
    op.drop_table('ipos')
