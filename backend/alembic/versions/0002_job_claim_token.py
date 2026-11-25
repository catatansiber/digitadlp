"""job claim token, label_set_by_reviewer

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('jobs') as b:
        b.add_column(sa.Column('claim_token', sa.String(length=32), nullable=True))
    with op.batch_alter_table('documents') as b:
        b.add_column(sa.Column('label_set_by_reviewer', sa.Boolean(), nullable=False,
                               server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('documents') as b:
        b.drop_column('label_set_by_reviewer')
    with op.batch_alter_table('jobs') as b:
        b.drop_column('claim_token')
