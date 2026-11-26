"""area_redactions: kotak sensor area pada halaman PDF

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'area_redactions',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('document_id', sa.String(length=32), sa.ForeignKey('documents.id'),
                  nullable=False),
        sa.Column('page', sa.Integer(), nullable=False),
        sa.Column('x0', sa.Float(), nullable=False),
        sa.Column('y0', sa.Float(), nullable=False),
        sa.Column('x1', sa.Float(), nullable=False),
        sa.Column('y1', sa.Float(), nullable=False),
        sa.Column('author_id', sa.String(length=32), sa.ForeignKey('users.id'),
                  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_area_redactions_document_id', 'area_redactions', ['document_id'])


def downgrade() -> None:
    op.drop_index('ix_area_redactions_document_id', table_name='area_redactions')
    op.drop_table('area_redactions')
