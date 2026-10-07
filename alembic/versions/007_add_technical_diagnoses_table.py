"""add technical diagnoses table

Revision ID: 007_add_technical_diagnoses_table
Revises: 006_add_mutual_funds_module
Create Date: 2026-10-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007_add_technical_diagnoses_table'
down_revision: Union[str, None] = '006_add_mutual_funds_module'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'technical_diagnoses',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('stop_loss', sa.Float(), nullable=False),
        sa.Column('trailing_stop', sa.Float(), nullable=True),
        sa.Column('target_1', sa.Float(), nullable=False),
        sa.Column('target_2', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='OPEN', nullable=False),
        sa.Column('closed_at_date', sa.Date(), nullable=True),
        sa.Column('hit_price', sa.Float(), nullable=True),
        sa.Column('hit_type', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'date', name='uq_technical_diagnosis_symbol_date')
    )
    with op.batch_alter_table('technical_diagnoses') as batch_op:
        batch_op.create_index('ix_technical_diagnoses_id', ['id'], unique=False)
        batch_op.create_index('ix_technical_diagnoses_date', ['date'], unique=False)
        batch_op.create_index('ix_technical_diagnoses_symbol', ['symbol'], unique=False)
        batch_op.create_index('ix_technical_diagnoses_status', ['status'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('technical_diagnoses') as batch_op:
        batch_op.drop_index('ix_technical_diagnoses_status')
        batch_op.drop_index('ix_technical_diagnoses_symbol')
        batch_op.drop_index('ix_technical_diagnoses_date')
        batch_op.drop_index('ix_technical_diagnoses_id')
    op.drop_table('technical_diagnoses')
