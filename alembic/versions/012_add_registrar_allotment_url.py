"""add registrar_allotment_url to ipos

Revision ID: 012_add_registrar_allotment_url
Revises: 011_add_user_auth_and_telegram_alert_flags
Create Date: 2026-10-16 12:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '012_add_registrar_allotment_url'
down_revision: Union[str, None] = '011_add_user_auth_and_telegram_alert_flags'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_columns = [c['name'] for c in insp.get_columns('ipos')]

    with op.batch_alter_table('ipos') as batch_op:
        if 'registrar_allotment_url' not in existing_columns:
            batch_op.add_column(
                sa.Column('registrar_allotment_url', sa.String(length=500), nullable=True)
            )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_columns = [c['name'] for c in insp.get_columns('ipos')]

    with op.batch_alter_table('ipos') as batch_op:
        if 'registrar_allotment_url' in existing_columns:
            batch_op.drop_column('registrar_allotment_url')
