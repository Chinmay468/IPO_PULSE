"""add ipo_aliases table for cross-source matching

Revision ID: 013_add_ipo_aliases
Revises: 012_add_registrar_allotment_url
Create Date: 2026-10-16 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '013_add_ipo_aliases'
down_revision: Union[str, None] = '012_add_registrar_allotment_url'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'ipo_aliases' not in tables:
        op.create_table(
            'ipo_aliases',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column('ipo_id', sa.Integer(), sa.ForeignKey('ipos.id', ondelete='CASCADE'), nullable=False),
            sa.Column('alias', sa.String(length=255), nullable=False),
            sa.Column('source', sa.String(length=50), server_default='manual', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_ipo_aliases_id', 'ipo_aliases', ['id'])
        op.create_index('ix_ipo_aliases_ipo_id', 'ipo_aliases', ['ipo_id'])
        op.create_index('ix_ipo_aliases_alias', 'ipo_aliases', ['alias'])


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if 'ipo_aliases' in tables:
        op.drop_index('ix_ipo_aliases_alias', table_name='ipo_aliases')
        op.drop_index('ix_ipo_aliases_ipo_id', table_name='ipo_aliases')
        op.drop_index('ix_ipo_aliases_id', table_name='ipo_aliases')
        op.drop_table('ipo_aliases')
