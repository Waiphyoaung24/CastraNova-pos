"""m007 m019 notification_preference notification_log user platform ids

Revision ID: 1a8ceda3b098
Revises: d40a4b91d505
Create Date: 2026-06-04 15:04:29.691002

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1a8ceda3b098'
down_revision = 'd40a4b91d505'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('notificationlog',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('channel', sa.Enum('LINE', 'VIBER', name='notificationchannel'), nullable=False),
    sa.Column('event_type', sa.Enum('LOW_STOCK', 'OVERRIDE_PENDING', 'PULL_FULFILLED', 'PULL_SHORT', name='notificationevent'), nullable=False),
    sa.Column('target_user_id', sa.Uuid(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Enum('SENT', 'FAILED', name='notificationstatus'), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('attempts >= 0', name='ck_notification_log_attempts_nn'),
    sa.ForeignKeyConstraint(['target_user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notification_log_status_created', 'notificationlog', ['status', 'created_at'], unique=False)
    op.create_index('ix_notification_log_target_user_id', 'notificationlog', ['target_user_id'], unique=False)
    op.create_table('notificationpreference',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('channel', sa.Enum('LINE', 'VIBER', name='notificationchannel'), nullable=False),
    sa.Column('event_type', sa.Enum('LOW_STOCK', 'OVERRIDE_PENDING', 'PULL_FULFILLED', 'PULL_SHORT', name='notificationevent'), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'channel', 'event_type', name='uq_notification_preference_user_channel_event')
    )
    op.create_index(op.f('ix_notificationpreference_user_id'), 'notificationpreference', ['user_id'], unique=False)
    op.add_column('user', sa.Column('line_user_id', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=True))
    op.add_column('user', sa.Column('viber_user_id', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=True))


def downgrade():
    op.drop_column('user', 'viber_user_id')
    op.drop_column('user', 'line_user_id')
    op.drop_index(op.f('ix_notificationpreference_user_id'), table_name='notificationpreference')
    op.drop_table('notificationpreference')
    op.drop_index('ix_notification_log_target_user_id', table_name='notificationlog')
    op.drop_index('ix_notification_log_status_created', table_name='notificationlog')
    # Irreversible by design: dropping notificationlog discards delivery history.
    op.drop_table('notificationlog')
    # Drop the enum types these tables introduced (mirrors the sibling M012
    # downgrade pattern). REVOKE for append-only enforcement is deferred to M021.
    sa.Enum(name='notificationstatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='notificationevent').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='notificationchannel').drop(op.get_bind(), checkfirst=True)
