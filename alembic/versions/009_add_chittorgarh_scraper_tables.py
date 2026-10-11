"""add chittorgarh scraper tables and fields

Revision ID: 009_add_chittorgarh_scraper_tables
Revises: 008_add_listing_price_to_ipos
Create Date: 2026-10-11 00:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '009_add_chittorgarh_scraper_tables'
down_revision: Union[str, None] = '008_add_listing_price_to_ipos'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = insp.get_table_names()
    existing_columns = [c['name'] for c in insp.get_columns('ipos')]

    # 1. Update ipos table
    with op.batch_alter_table('ipos') as batch_op:
        if 'source' not in existing_columns:
            batch_op.add_column(sa.Column('source', sa.String(50), nullable=True))
        if 'source_url' not in existing_columns:
            batch_op.add_column(sa.Column('source_url', sa.String(500), nullable=True))
        if 'source_id' not in existing_columns:
            batch_op.add_column(sa.Column('source_id', sa.Integer(), nullable=True))
            batch_op.create_index('ix_ipos_source_id', ['source_id'], unique=False)
        if 'fetched_at' not in existing_columns:
            batch_op.add_column(sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True))
        if 'data_quality' not in existing_columns:
            batch_op.add_column(sa.Column('data_quality', sa.JSON(), nullable=True))

    # 2. ipo_documents table
    if 'ipo_documents' not in existing_tables:
        op.create_table(
            'ipo_documents',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('ipo_id', sa.Integer(), sa.ForeignKey('ipos.id', ondelete='CASCADE'), nullable=False),
            sa.Column('type', sa.String(20), nullable=False),
            sa.Column('url', sa.String(500), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_ipo_documents_ipo_id', 'ipo_documents', ['ipo_id'], unique=False)

    # 3. ipo_anchor table
    if 'ipo_anchor' not in existing_tables:
        op.create_table(
            'ipo_anchor',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('ipo_id', sa.Integer(), sa.ForeignKey('ipos.id', ondelete='CASCADE'), nullable=False),
            sa.Column('investor', sa.String(255), nullable=False),
            sa.Column('amount', sa.Float(), nullable=True),
            sa.Column('lock_in_end', sa.Date(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_ipo_anchor_ipo_id', 'ipo_anchor', ['ipo_id'], unique=False)

    # 4. ipo_reviews_summary table
    if 'ipo_reviews_summary' not in existing_tables:
        op.create_table(
            'ipo_reviews_summary',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('ipo_id', sa.Integer(), sa.ForeignKey('ipos.id', ondelete='CASCADE'), nullable=False),
            sa.Column('apply', sa.Integer(), server_default='0', nullable=False),
            sa.Column('may_apply', sa.Integer(), server_default='0', nullable=False),
            sa.Column('neutral', sa.Integer(), server_default='0', nullable=False),
            sa.Column('avoid', sa.Integer(), server_default='0', nullable=False),
            sa.Column('not_rated', sa.Integer(), server_default='0', nullable=False),
            sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_ipo_reviews_summary_ipo_id', 'ipo_reviews_summary', ['ipo_id'], unique=True)

    # 5. ipo_listing table
    if 'ipo_listing' not in existing_tables:
        op.create_table(
            'ipo_listing',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('ipo_id', sa.Integer(), sa.ForeignKey('ipos.id', ondelete='CASCADE'), nullable=False),
            sa.Column('listing_price', sa.Float(), nullable=True),
            sa.Column('listing_gain_pct', sa.Float(), nullable=True),
            sa.Column('listing_date', sa.Date(), nullable=True),
            sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_ipo_listing_ipo_id', 'ipo_listing', ['ipo_id'], unique=True)


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = insp.get_table_names()

    if 'ipo_listing' in existing_tables:
        op.drop_table('ipo_listing')
    if 'ipo_reviews_summary' in existing_tables:
        op.drop_table('ipo_reviews_summary')
    if 'ipo_anchor' in existing_tables:
        op.drop_table('ipo_anchor')
    if 'ipo_documents' in existing_tables:
        op.drop_table('ipo_documents')

    existing_columns = [c['name'] for c in insp.get_columns('ipos')]
    with op.batch_alter_table('ipos') as batch_op:
        if 'source_id' in existing_columns:
            batch_op.drop_index('ix_ipos_source_id')
            batch_op.drop_column('source_id')
        if 'source_url' in existing_columns:
            batch_op.drop_column('source_url')
        if 'source' in existing_columns:
            batch_op.drop_column('source')
        if 'fetched_at' in existing_columns:
            batch_op.drop_column('fetched_at')
        if 'data_quality' in existing_columns:
            batch_op.drop_column('data_quality')
