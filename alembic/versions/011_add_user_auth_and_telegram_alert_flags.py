"""add user auth table and telegram alert flags

Revision ID: 011_add_user_auth_and_telegram_alert_flags
Revises: 010_add_seed_and_dates_tba_flags
Create Date: 2026-10-13 19:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '011_add_user_auth_and_telegram_alert_flags'
down_revision: Union[str, None] = '010_add_seed_and_dates_tba_flags'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = insp.get_table_names()

    # 1. Create `users` table if not exists
    if 'users' not in existing_tables:
        op.create_table(
            'users',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('username', sa.String(length=100), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('hashed_password', sa.String(length=255), nullable=False),
            sa.Column('full_name', sa.String(length=255), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
            sa.Column('is_superuser', sa.Boolean(), server_default=sa.text('0'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('username', name='uq_users_username'),
            sa.UniqueConstraint('email', name='uq_users_email')
        )
        with op.batch_alter_table('users') as batch_op:
            batch_op.create_index('ix_users_id', ['id'], unique=False)
            batch_op.create_index('ix_users_username', ['username'], unique=True)
            batch_op.create_index('ix_users_email', ['email'], unique=True)

    # 2. Add telegram alert columns to `ipos` table
    ipos_columns = [c['name'] for c in insp.get_columns('ipos')]
    with op.batch_alter_table('ipos') as batch_op:
        if 'telegram_alert_sent' not in ipos_columns:
            batch_op.add_column(
                sa.Column('telegram_alert_sent', sa.Boolean(), server_default=sa.text('0'), nullable=False)
            )
            batch_op.create_index('ix_ipos_telegram_alert_sent', ['telegram_alert_sent'], unique=False)
        if 'telegram_alert_sent_at' not in ipos_columns:
            batch_op.add_column(
                sa.Column('telegram_alert_sent_at', sa.DateTime(timezone=True), nullable=True)
            )

    # 3. Add `user_id` to `portfolio_holdings`
    if 'portfolio_holdings' in existing_tables:
        holdings_columns = [c['name'] for c in insp.get_columns('portfolio_holdings')]
        with op.batch_alter_table('portfolio_holdings') as batch_op:
            if 'user_id' not in holdings_columns:
                batch_op.add_column(
                    sa.Column('user_id', sa.Integer(), nullable=True)
                )
                batch_op.create_foreign_key(
                    'fk_portfolio_holdings_user_id',
                    'users',
                    ['user_id'],
                    ['id'],
                    ondelete='CASCADE'
                )
                batch_op.create_index('ix_portfolio_holdings_user_id', ['user_id'], unique=False)

    # 4. Add `user_id` to `mf_holdings`
    if 'mf_holdings' in existing_tables:
        mf_columns = [c['name'] for c in insp.get_columns('mf_holdings')]
        with op.batch_alter_table('mf_holdings') as batch_op:
            if 'user_id' not in mf_columns:
                batch_op.add_column(
                    sa.Column('user_id', sa.Integer(), nullable=True)
                )
                batch_op.create_foreign_key(
                    'fk_mf_holdings_user_id',
                    'users',
                    ['user_id'],
                    ['id'],
                    ondelete='CASCADE'
                )
                batch_op.create_index('ix_mf_holdings_user_id', ['user_id'], unique=False)

    # 5. Add `user_id` to `portfolio_snapshots`
    if 'portfolio_snapshots' in existing_tables:
        snap_columns = [c['name'] for c in insp.get_columns('portfolio_snapshots')]
        with op.batch_alter_table('portfolio_snapshots') as batch_op:
            if 'user_id' not in snap_columns:
                batch_op.add_column(
                    sa.Column('user_id', sa.Integer(), nullable=True)
                )
                batch_op.create_foreign_key(
                    'fk_portfolio_snapshots_user_id',
                    'users',
                    ['user_id'],
                    ['id'],
                    ondelete='CASCADE'
                )
                batch_op.create_index('ix_portfolio_snapshots_user_id', ['user_id'], unique=False)

    # 6. Seed default admin user if none exists and migrate unassigned holdings
    res = conn.execute(sa.text("SELECT id FROM users WHERE username = 'admin'")).fetchone()
    if not res:
        conn.execute(sa.text(
            "INSERT INTO users (username, hashed_password, full_name, is_active, is_superuser) "
            "VALUES ('admin', '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9', 'Administrator', 1, 1)"
        ))
        res = conn.execute(sa.text("SELECT id FROM users WHERE username = 'admin'")).fetchone()

    if res:
        admin_id = res[0]
        # Safely assign existing orphan portfolio data to admin
        if 'portfolio_holdings' in existing_tables:
            conn.execute(sa.text(f"UPDATE portfolio_holdings SET user_id = {admin_id} WHERE user_id IS NULL"))
        if 'mf_holdings' in existing_tables:
            conn.execute(sa.text(f"UPDATE mf_holdings SET user_id = {admin_id} WHERE user_id IS NULL"))
        if 'portfolio_snapshots' in existing_tables:
            conn.execute(sa.text(f"UPDATE portfolio_snapshots SET user_id = {admin_id} WHERE user_id IS NULL"))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = insp.get_table_names()

    if 'portfolio_snapshots' in existing_tables:
        snap_columns = [c['name'] for c in insp.get_columns('portfolio_snapshots')]
        with op.batch_alter_table('portfolio_snapshots') as batch_op:
            if 'user_id' in snap_columns:
                batch_op.drop_index('ix_portfolio_snapshots_user_id')
                batch_op.drop_constraint('fk_portfolio_snapshots_user_id', type_='foreignkey')
                batch_op.drop_column('user_id')

    if 'mf_holdings' in existing_tables:
        mf_columns = [c['name'] for c in insp.get_columns('mf_holdings')]
        with op.batch_alter_table('mf_holdings') as batch_op:
            if 'user_id' in mf_columns:
                batch_op.drop_index('ix_mf_holdings_user_id')
                batch_op.drop_constraint('fk_mf_holdings_user_id', type_='foreignkey')
                batch_op.drop_column('user_id')

    if 'portfolio_holdings' in existing_tables:
        holdings_columns = [c['name'] for c in insp.get_columns('portfolio_holdings')]
        with op.batch_alter_table('portfolio_holdings') as batch_op:
            if 'user_id' in holdings_columns:
                batch_op.drop_index('ix_portfolio_holdings_user_id')
                batch_op.drop_constraint('fk_portfolio_holdings_user_id', type_='foreignkey')
                batch_op.drop_column('user_id')

    if 'ipos' in existing_tables:
        ipos_columns = [c['name'] for c in insp.get_columns('ipos')]
        with op.batch_alter_table('ipos') as batch_op:
            if 'telegram_alert_sent_at' in ipos_columns:
                batch_op.drop_column('telegram_alert_sent_at')
            if 'telegram_alert_sent' in ipos_columns:
                batch_op.drop_index('ix_ipos_telegram_alert_sent')
                batch_op.drop_column('telegram_alert_sent')

    if 'users' in existing_tables:
        with op.batch_alter_table('users') as batch_op:
            batch_op.drop_index('ix_users_email')
            batch_op.drop_index('ix_users_username')
            batch_op.drop_index('ix_users_id')
        op.drop_table('users')
