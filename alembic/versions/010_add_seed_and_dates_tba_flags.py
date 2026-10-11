"""add is_seed and dates_tba flags to ipos

Revision ID: 010_add_seed_and_dates_tba_flags
Revises: 009_add_chittorgarh_scraper_tables
Create Date: 2026-10-11 08:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010_add_seed_and_dates_tba_flags'
down_revision: Union[str, None] = '009_add_chittorgarh_scraper_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_columns = [c['name'] for c in insp.get_columns('ipos')]

    with op.batch_alter_table('ipos') as batch_op:
        if 'is_seed' not in existing_columns:
            batch_op.add_column(
                sa.Column('is_seed', sa.Boolean(), server_default=sa.text('0'), nullable=False)
            )
            batch_op.create_index('ix_ipos_is_seed', ['is_seed'], unique=False)

        if 'dates_tba' not in existing_columns:
            batch_op.add_column(
                sa.Column('dates_tba', sa.Boolean(), server_default=sa.text('0'), nullable=False)
            )
            batch_op.create_index('ix_ipos_dates_tba', ['dates_tba'], unique=False)

    # Mark existing seed rows (rows with NULL source are historical seed records)
    conn.execute(sa.text("UPDATE ipos SET is_seed = 1 WHERE source IS NULL"))

    # Mark existing IPOs with missing dates as dates_tba = 1
    conn.execute(sa.text("UPDATE ipos SET dates_tba = 1 WHERE open_date IS NULL AND close_date IS NULL"))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_columns = [c['name'] for c in insp.get_columns('ipos')]

    with op.batch_alter_table('ipos') as batch_op:
        if 'dates_tba' in existing_columns:
            batch_op.drop_index('ix_ipos_dates_tba')
            batch_op.drop_column('dates_tba')
        if 'is_seed' in existing_columns:
            batch_op.drop_index('ix_ipos_is_seed')
            batch_op.drop_column('is_seed')
