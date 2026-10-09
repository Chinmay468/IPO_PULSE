"""add listing_price to ipos table

Revision ID: 008_add_listing_price_to_ipos
Revises: 007_add_technical_diagnoses_table
Create Date: 2026-10-09 17:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '008_add_listing_price_to_ipos'
down_revision: Union[str, None] = '007_add_technical_diagnoses_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [c['name'] for c in insp.get_columns('ipos')]
    if 'listing_price' not in columns:
        with op.batch_alter_table('ipos') as batch_op:
            batch_op.add_column(sa.Column('listing_price', sa.Float(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [c['name'] for c in insp.get_columns('ipos')]
    if 'listing_price' in columns:
        with op.batch_alter_table('ipos') as batch_op:
            batch_op.drop_column('listing_price')
