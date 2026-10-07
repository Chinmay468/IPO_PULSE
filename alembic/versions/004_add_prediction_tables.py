"""add prediction tables

Revision ID: 004_add_prediction_tables
Revises: 003_add_suggestion_log
Create Date: 2026-10-05 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_add_prediction_tables'
down_revision: Union[str, None] = '003_add_suggestion_log'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'predictions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('target_date', sa.Date(), nullable=False),
        sa.Column('symbol', sa.String(length=50), nullable=False),
        sa.Column('model_name', sa.String(length=50), nullable=False),
        sa.Column('predicted_direction', sa.Enum('UP', 'DOWN', 'FLAT', name='directiontype'), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('features_hash', sa.String(length=64), nullable=True),
        sa.Column('locked', sa.Boolean(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('target_date', 'symbol', 'model_name', name='uq_prediction_target_symbol_model')
    )
    with op.batch_alter_table('predictions') as batch_op:
        batch_op.create_index('ix_predictions_id', ['id'], unique=False)
        batch_op.create_index('ix_predictions_target_date', ['target_date'], unique=False)
        batch_op.create_index('ix_predictions_symbol', ['symbol'], unique=False)
        batch_op.create_index('ix_predictions_model_name', ['model_name'], unique=False)

    op.create_table(
        'prediction_results',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('prediction_id', sa.Integer(), nullable=False),
        sa.Column('actual_close', sa.Float(), nullable=False),
        sa.Column('actual_return', sa.Float(), nullable=False),
        sa.Column('correct', sa.Boolean(), nullable=False),
        sa.Column('scored_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['prediction_id'], ['predictions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('prediction_id')
    )
    with op.batch_alter_table('prediction_results') as batch_op:
        batch_op.create_index('ix_prediction_results_id', ['id'], unique=False)
        batch_op.create_index('ix_prediction_results_prediction_id', ['prediction_id'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('prediction_results') as batch_op:
        batch_op.drop_index('ix_prediction_results_prediction_id')
        batch_op.drop_index('ix_prediction_results_id')
    op.drop_table('prediction_results')

    with op.batch_alter_table('predictions') as batch_op:
        batch_op.drop_index('ix_predictions_model_name')
        batch_op.drop_index('ix_predictions_symbol')
        batch_op.drop_index('ix_predictions_target_date')
        batch_op.drop_index('ix_predictions_id')
    op.drop_table('predictions')
