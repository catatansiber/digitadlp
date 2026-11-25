"""documents.return_reason

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('documents') as b:
        b.add_column(sa.Column('return_reason', sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('documents') as b:
        b.drop_column('return_reason')
